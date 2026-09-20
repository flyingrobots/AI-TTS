# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Every settings write is validated at one boundary.

A settings update arrives over the socket as arbitrary JSON, and each key has
its own notion of valid: a voice must exist in the engine's catalog, a
playback rate must be one of a finite set, a cache ceiling must be a whole
count of bytes and not a float that happens to look like one. Those rules used
to be interleaved with the daemon's operation set, so nothing could exercise
them without standing up a daemon, a store, an engine and a sink — which is
why several of them had no test at all.

Two of these keys are not really settings. Writing ``playback_rate`` changes
the live controller and ``cache_max_bytes`` can evict files, and the tests
below assert those effects happen rather than trusting that they do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aitts.ipc import ApiError
from aitts.settings import (
    SPEED_MAX,
    SPEED_MIN,
    SettingsService,
    parse_cache_limit,
    parse_playback_rate,
    parse_speed,
)

if TYPE_CHECKING:
    from aitts.store import Store

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the settings contract in architecture section 5"),
]


class FakeEnvironment:
    """The live components a settings write can reach, under test control."""

    def __init__(self, *, voices: tuple[str, ...] = ("bm_daniel", "af_heart")) -> None:
        self.voices = voices
        self.rate = 1.0
        self.rates_set: list[float] = []
        self.cache_enforcements = 0

    def available_voices(self) -> list[str]:
        return list(self.voices)

    def default_voice(self) -> str:
        return self.voices[0] if self.voices else ""

    def playback_rate(self) -> float:
        return self.rate

    def set_playback_rate(self, rate: float) -> None:
        self.rate = rate
        self.rates_set.append(rate)

    def enforce_cache_limit(self) -> None:
        self.cache_enforcements += 1


@pytest.fixture
def environment() -> FakeEnvironment:
    return FakeEnvironment()


@pytest.fixture
def settings(store: Store, environment: FakeEnvironment) -> SettingsService:
    return SettingsService(store, environment)


def test_defaults_are_reported_before_anything_is_written(
    settings: SettingsService,
) -> None:
    values = settings.values()

    # A client reads this to build its settings view, so every key has to be
    # present and answerable on a fresh install.
    assert values["voice"] == "bm_daniel"
    assert values["speed"] == 1.0
    assert values["captions_enabled"] is False
    assert values["captions_enabled_configured"] is False
    assert values["input_interrupt_enabled"] is True
    assert values["input_interrupt_resume"] == "when_idle"


def test_an_unknown_setting_is_refused_rather_than_ignored(
    settings: SettingsService,
) -> None:
    with pytest.raises(ApiError) as raised:
        settings.apply({"volume": 11})

    # A client that misspells a key and is told nothing has no way to discover
    # that its preference was never recorded.
    assert "volume" in str(raised.value)


@pytest.mark.parametrize(
    "update",
    [
        {"voice": "af_heart", "nonsense": 1},
        {"voice": "af_heart", "speed": 99},
        {"voice": "af_heart", "captions_enabled": "yes"},
    ],
)
def test_a_rejected_update_writes_nothing(
    settings: SettingsService, update: dict[str, object]
) -> None:
    with pytest.raises(ApiError):
        settings.apply(update)

    # Applying the valid half of a rejected request leaves the client showing
    # an error while its state has silently moved: it asked for two changes,
    # was told no, and got one of them.
    assert settings.values()["voice"] == "bm_daniel"


def test_a_rejected_update_has_no_side_effects_either(
    settings: SettingsService, environment: FakeEnvironment
) -> None:
    with pytest.raises(ApiError):
        settings.apply({"playback_rate": 1.5, "cache_max_bytes": -1})

    # The live effects have to be held back too, or a rejected request still
    # changes the rate mid-clip.
    assert environment.rates_set == []
    assert environment.cache_enforcements == 0


# -- voice ----------------------------------------------------------------


def test_a_voice_outside_the_engine_catalog_is_refused(settings: SettingsService) -> None:
    with pytest.raises(ApiError) as raised:
        settings.apply({"voice": "qq_nobody"})

    assert "qq_nobody" in str(raised.value)
    assert settings.values()["voice"] == "bm_daniel"


def test_a_voice_in_the_catalog_is_recorded(settings: SettingsService) -> None:
    settings.apply({"voice": "af_heart"})

    assert settings.speaking_voice() == "af_heart"


# -- speed ----------------------------------------------------------------


@pytest.mark.parametrize("declared", [0.5, 1.0, 2.0, 1, 2])
def test_a_speed_inside_the_engine_range_is_accepted(
    settings: SettingsService, declared: float
) -> None:
    settings.apply({"speed": declared})

    assert settings.speaking_speed() == float(declared)


@pytest.mark.parametrize("declared", [0.49, 2.01, 0, -1, 99, "1.0", None, True])
def test_a_speed_outside_the_engine_range_is_refused(
    settings: SettingsService, declared: object
) -> None:
    with pytest.raises(ApiError) as raised:
        settings.apply({"speed": declared})

    # Outside this range the voice stops being intelligible, which the
    # listener cannot diagnose from the audio. True is refused with the rest:
    # a bool is an int in Python, and speed=true meaning 1.0 is a coincidence.
    assert str(SPEED_MIN) in str(raised.value)
    assert str(SPEED_MAX) in str(raised.value)
    assert settings.speaking_speed() == 1.0


# -- playback rate reaches the live controller ----------------------------


def test_a_playback_rate_is_applied_to_the_controller_not_the_table(
    settings: SettingsService, environment: FakeEnvironment
) -> None:
    settings.apply({"playback_rate": 1.5})

    # It must take effect mid-clip, so the controller owns it; a value written
    # only to the table would be silently ignored until the next restart.
    assert environment.rates_set == [1.5]
    assert settings.values()["playback_rate"] == 1.5


def test_a_playback_rate_that_is_not_offered_is_refused(
    settings: SettingsService, environment: FakeEnvironment
) -> None:
    with pytest.raises(ApiError) as raised:
        settings.apply({"playback_rate": 1.25})

    assert "1.5" in str(raised.value)
    assert environment.rates_set == []


# -- cache ceiling --------------------------------------------------------


def test_lowering_the_cache_ceiling_evicts_immediately(
    settings: SettingsService, environment: FakeEnvironment
) -> None:
    settings.apply({"cache_max_bytes": 4096})

    # A lowered ceiling that evicts nothing until the next clip is not a
    # ceiling; it is a note about one.
    assert settings.cache_limit() == 4096
    assert environment.cache_enforcements == 1


@pytest.mark.parametrize("declared", [-1, 12.5, "1e6", "12.5", "", True, None, [1]])
def test_a_cache_ceiling_that_is_not_a_byte_count_is_refused(
    settings: SettingsService, environment: FakeEnvironment, declared: object
) -> None:
    with pytest.raises(ApiError):
        settings.apply({"cache_max_bytes": declared})

    assert environment.cache_enforcements == 0


def test_a_corrupt_stored_ceiling_falls_back_to_the_default(
    store: Store, settings: SettingsService
) -> None:
    store.set_setting("cache_max_bytes", "not a number")

    # Reading must not raise: this value is on the path of every finished
    # clip, and a store somebody edited by hand cannot stop playback.
    assert settings.cache_limit() > 0


# -- the strictly boolean settings ----------------------------------------


@pytest.mark.parametrize("key", ["captions_enabled", "input_interrupt_enabled"])
@pytest.mark.parametrize("declared", [1, 0, "true", "", None, [], 1.0])
def test_a_boolean_setting_refuses_anything_merely_truthy(
    settings: SettingsService, key: str, declared: object
) -> None:
    with pytest.raises(ApiError) as raised:
        settings.apply({key: declared})

    # "1" and "true" are how a shell would express this, and accepting them
    # would make "0" and "false" mean their opposites.
    assert key in str(raised.value)


@pytest.mark.parametrize("key", ["captions_enabled", "input_interrupt_enabled"])
def test_a_boolean_setting_round_trips(settings: SettingsService, key: str) -> None:
    settings.apply({key: False})
    assert settings.values()[key] is False

    settings.apply({key: True})
    assert settings.values()[key] is True


def test_captions_record_that_they_were_configured(settings: SettingsService) -> None:
    assert settings.values()["captions_enabled_configured"] is False

    settings.apply({"captions_enabled": False})

    # Explicitly off and never chosen look the same in the value alone, and
    # the client shows a first-run prompt for one of them.
    assert settings.values()["captions_enabled_configured"] is True


# -- the resume policy ----------------------------------------------------


@pytest.mark.parametrize("policy", ["manual", "when_idle"])
def test_an_offered_resume_policy_is_recorded(settings: SettingsService, policy: str) -> None:
    settings.apply({"input_interrupt_resume": policy})

    assert settings.input_interrupt_resume() == policy


@pytest.mark.parametrize("policy", ["auto", "", "MANUAL", True, 1])
def test_an_unoffered_resume_policy_is_refused(settings: SettingsService, policy: object) -> None:
    with pytest.raises(ApiError) as raised:
        settings.apply({"input_interrupt_resume": policy})

    assert "manual" in str(raised.value)
    assert settings.input_interrupt_resume() == "when_idle"


# -- the parsers, at their edges ------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0),
        ("0", 0),
        (4096, 4096),
        ("4096", 4096),
        (" 4096 ", 4096),
        (-1, None),
        ("-1", None),
        (12.5, None),
        ("12.5", None),
        ("1e6", None),
        ("", None),
        (True, None),
        (None, None),
    ],
)
def test_the_cache_limit_parser_at_its_edges(raw: object, expected: int | None) -> None:
    assert parse_cache_limit(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.5, 0.5), (1, 1.0), (3, 3.0), (1.25, None), (0, None), (True, None), ("1.0", None)],
)
def test_the_playback_rate_parser_at_its_edges(raw: object, expected: float | None) -> None:
    assert parse_playback_rate(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.5, 0.5), (2.0, 2.0), (1, 1.0), (0.49, None), (2.01, None), (True, None), ("1", None)],
)
def test_the_speed_parser_at_its_edges(raw: object, expected: float | None) -> None:
    assert parse_speed(raw) == expected
