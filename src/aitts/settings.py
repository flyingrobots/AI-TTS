# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The settings table: what may be written to it, and what writing means.

Split out of the daemon because it was the largest thing in there that has
nothing to do with queues. Two properties are worth the seam.

The first is that every setting is validated at one boundary. A settings
update arrives over the socket as arbitrary JSON, and each key has a
different notion of valid: a voice must exist in the engine's catalog, a
playback rate must be one of a finite set, a cache limit must be a
non-negative integer and not a float that happens to look like one. Those
rules were interleaved with the operation set, so nothing could exercise them
without standing up a whole daemon.

The second is that two settings are not really *settings*. Writing
``playback_rate`` changes the live playback controller and ``cache_max_bytes``
can evict files. Rather than reach for those collaborators directly, the
service names what it needs as :class:`SettingsEnvironment` — one seam, so
the validation is testable against a fake and the effects stay visible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aitts.application.cache import DEFAULT_CACHE_MAX_BYTES
from aitts.ipc import BAD_REQUEST, ApiError
from aitts.playback import PLAYBACK_RATES

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.store import Store

# How a hold the listener's voice caused is released: only on their word, or
# by itself once the microphone goes quiet.
INPUT_INTERRUPT_RESUME_POLICIES = ("manual", "when_idle")

# The engine's usable range for voice-generation speed. Outside it the voice
# stops being intelligible, and one message serves both the submit path and a
# settings write so a client cannot be told two different things.
SPEED_MIN = 0.5
SPEED_MAX = 2.0
SPEED_MESSAGE = f"speed must be a number between {SPEED_MIN} and {SPEED_MAX}"


class SettingsEnvironment(Protocol):
    """The live components a settings write can reach.

    Named as one seam rather than injected as four callables, so the effects a
    settings write has outside the settings table are visible in one place.
    """

    def available_voices(self) -> list[str]:
        """Voices the configured engine accepts."""
        ...

    def default_voice(self) -> str:
        """Return the voice to report when none has been chosen."""
        ...

    def playback_rate(self) -> float:
        """Return the live playback rate, which the controller owns, not the table."""
        ...

    def set_playback_rate(self, rate: float) -> None:
        """Change the live playback rate."""
        ...

    def enforce_cache_limit(self) -> None:
        """Bring the cache back under its configured cap."""
        ...


class SettingsService:
    """Read and validate the settings table, applying what a write implies."""

    def __init__(self, store: Store, environment: SettingsEnvironment) -> None:
        """Create the service over ``store``, reaching live state via ``environment``."""
        self._store = store
        self._environment = environment

    def values(self) -> dict[str, object]:
        """Every setting, as the wire reports it."""
        return {
            "voice": self._store.get_setting("voice", self._environment.default_voice()),
            "speed": float(self._store.get_setting("speed", "1.0")),
            "playback_rate": self._environment.playback_rate(),
            "cache_max_bytes": self.cache_limit(),
            "captions_enabled": self.captions_enabled(),
            "captions_enabled_configured": self._store.has_setting("captions_enabled"),
            "input_interrupt_enabled": self.input_interrupt_enabled(),
            "input_interrupt_resume": self.input_interrupt_resume(),
        }

    def apply(self, updates: dict[str, object]) -> None:
        """Validate every update, then apply them, or reject the request whole.

        An unknown key is refused rather than ignored. A client that misspells
        a setting and is told nothing has no way to discover that its
        preference was never recorded.

        Validation completes before anything is written. Applying the valid
        half of a rejected request leaves the client showing an error while
        its state has silently moved: it asked for two changes, was told no,
        and got one of them.
        """
        planners: dict[str, Callable[[object], Callable[[], None]]] = {
            "voice": self._plan_voice,
            "speed": self._plan_speed,
            "cache_max_bytes": self._plan_cache_limit,
            "playback_rate": self._plan_playback_rate,
            "captions_enabled": self._plan_captions_enabled,
            "input_interrupt_enabled": self._plan_input_interrupt_enabled,
            "input_interrupt_resume": self._plan_input_interrupt_resume,
        }
        planned: list[Callable[[], None]] = []
        for key, value in updates.items():
            planner = planners.get(key)
            if planner is None:
                msg = f"unknown setting {key!r}"
                raise ApiError(BAD_REQUEST, msg)
            planned.append(planner(value))
        for effect in planned:
            effect()

    # -- individual reads, for callers that want one value ----------------

    def cache_limit(self) -> int:
        """Return the configured cache ceiling in bytes."""
        raw = self._store.get_setting("cache_max_bytes", str(DEFAULT_CACHE_MAX_BYTES))
        parsed = parse_cache_limit(raw)
        return DEFAULT_CACHE_MAX_BYTES if parsed is None else parsed

    def captions_enabled(self) -> bool:
        """Whether captions are showing."""
        return self._store.get_setting("captions_enabled", "false") == "true"

    def input_interrupt_enabled(self) -> bool:
        """Whether the listener's own voice stops playback."""
        return self._store.get_setting("input_interrupt_enabled", "true") == "true"

    def input_interrupt_resume(self) -> str:
        """How a hold the listener's voice caused is released."""
        return self._store.get_setting("input_interrupt_resume", "when_idle")

    def speaking_voice(self) -> str:
        """Return the voice to speak with when a client names none."""
        return self._store.get_setting("voice", self._environment.default_voice())

    def speaking_speed(self) -> float:
        """Return the speed to synthesize at when a client names none."""
        return float(self._store.get_setting("speed", "1.0"))

    # -- one validator per setting ----------------------------------------

    def _plan_voice(self, value: object) -> Callable[[], None]:
        if value not in self._environment.available_voices():
            msg = f"unknown voice {value!r}"
            raise ApiError(BAD_REQUEST, msg)
        return lambda: self._store.set_setting("voice", str(value))

    def _plan_speed(self, value: object) -> Callable[[], None]:
        speed = parse_speed(value)
        if speed is None:
            raise ApiError(BAD_REQUEST, SPEED_MESSAGE)
        return lambda: self._store.set_setting("speed", str(speed))

    def _plan_cache_limit(self, value: object) -> Callable[[], None]:
        limit = parse_cache_limit(value)
        if limit is None:
            msg = "'cache_max_bytes' must be a non-negative integer"
            raise ApiError(BAD_REQUEST, msg)
        return lambda: self._write_cache_limit(limit)

    def _write_cache_limit(self, limit: int) -> None:
        self._store.set_setting("cache_max_bytes", str(limit))
        # A lowered ceiling that evicts nothing until the next clip is not a
        # ceiling; it is a note about one.
        self._environment.enforce_cache_limit()

    def _plan_playback_rate(self, value: object) -> Callable[[], None]:
        rate = parse_playback_rate(value)
        if rate is None:
            choices = ", ".join(f"{choice:g}" for choice in PLAYBACK_RATES)
            msg = f"'playback_rate' must be one of: {choices}"
            raise ApiError(BAD_REQUEST, msg)
        # The controller owns this one: it must take effect mid-clip.
        return lambda: self._environment.set_playback_rate(rate)

    def _plan_captions_enabled(self, value: object) -> Callable[[], None]:
        stored = _boolean("captions_enabled", value)
        return lambda: self._store.set_setting("captions_enabled", stored)

    def _plan_input_interrupt_enabled(self, value: object) -> Callable[[], None]:
        stored = _boolean("input_interrupt_enabled", value)
        return lambda: self._store.set_setting("input_interrupt_enabled", stored)

    def _plan_input_interrupt_resume(self, value: object) -> Callable[[], None]:
        if value not in INPUT_INTERRUPT_RESUME_POLICIES:
            choices = ", ".join(INPUT_INTERRUPT_RESUME_POLICIES)
            msg = f"'input_interrupt_resume' must be one of: {choices}"
            raise ApiError(BAD_REQUEST, msg)
        return lambda: self._store.set_setting("input_interrupt_resume", str(value))


def _boolean(key: str, value: object) -> str:
    """Render a strictly-boolean setting, refusing anything truthy-but-not-bool."""
    if type(value) is not bool:
        msg = f"{key!r} must be a boolean"
        raise ApiError(BAD_REQUEST, msg)
    return "true" if value else "false"


def parse_speed(raw: object) -> float | None:
    """Read a voice-generation speed, or ``None`` when it is not a usable one.

    ``bool`` is excluded deliberately: it is an ``int`` in Python, and
    ``speed=True`` meaning 1.0 is a coincidence rather than an intention.

    The range is the engine's, not a preference. Outside it the voice stops
    being intelligible, which is a failure the listener cannot diagnose from
    the audio, so it is refused where it was typed instead.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    speed = float(raw)
    return speed if SPEED_MIN <= speed <= SPEED_MAX else None


def parse_playback_rate(raw: object) -> float | None:
    """Read a playback rate, or ``None`` when it is not one of the offered rates."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    rate = float(raw)
    return rate if rate in PLAYBACK_RATES else None


def parse_cache_limit(raw: object) -> int | None:
    """Read a cache ceiling in bytes, or ``None`` when it is not a whole count.

    A string is accepted because that is how the setting is stored, but only
    when it round-trips exactly: ``"1e6"`` and ``"12.5"`` are refused rather
    than silently truncated into a ceiling nobody asked for.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    if isinstance(raw, str) and raw.strip() != str(limit):
        return None
    return limit if limit >= 0 else None
