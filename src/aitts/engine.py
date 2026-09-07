# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The engine boundary: a small interface with one real implementation.

The engine is a detail, not the architecture (architecture.md §8). The daemon
decides *what may be spoken by whom* from the utterance's sensitivity; an
engine is never asked to make that call.
"""

from __future__ import annotations

import threading
import time
import wave
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from aitts.model import Sensitivity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class SynthesisError(Exception):
    """Raised when an engine cannot render text to audio."""


@runtime_checkable
class Engine(Protocol):
    """What any synthesis engine must provide."""

    name: str
    is_local: bool

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Render ``text`` to a WAV file at ``out_path``; return duration in ms."""
        ...

    def list_voices(self) -> list[str]:
        """Enumerate voice identifiers. The UI enumerates, never hardcodes."""
        ...

    def warmup(self) -> None:
        """Load whatever must be resident so first synthesis is not cold."""
        ...


@runtime_checkable
class PreparingEngine(Protocol):
    """An engine that can say whether it is still getting ready.

    Deliberately separate from :class:`Engine`. Fetching model weights is a
    property of one adapter, not of the boundary, and requiring every engine
    to answer a question only one of them has would put an implementation
    detail into the port. Callers probe for it and treat its absence as ready.
    """

    def preparation(self) -> tuple[str, float] | None:
        """Return the asset being fetched and when that started, or ``None``."""
        ...


def engine_preparation(engine: object) -> dict[str, object] | None:
    """Describe what ``engine`` is still fetching, in snapshot shape.

    ``None`` for a ready engine *and* for one that cannot report, which are
    the same thing to a caller: nothing is known to be outstanding.
    """
    if not isinstance(engine, PreparingEngine):
        return None
    reported = engine.preparation()
    if reported is None:
        return None
    asset, since = reported
    return {"asset": asset, "since": since}


def eligible_engine_names(engines: Mapping[str, Engine], sensitivity: Sensitivity) -> list[str]:
    """Engines permitted to speak text of the given sensitivity.

    Only public text may leave the machine; internal and confidential text is
    local-only, always (architecture.md §9).
    """
    if sensitivity is Sensitivity.PUBLIC:
        return list(engines)
    return [name for name, engine in engines.items() if engine.is_local]


class FakeEngine:
    """A deterministic in-memory engine for tests: fast, controllable, honest."""

    name = "fake"
    is_local = True

    def __init__(
        self,
        voices: list[str],
        *,
        duration_ms: int = 100,
        delay_s: float = 0.0,
        fail_texts: frozenset[str] | set[str] | None = None,
    ) -> None:
        """Create a fake engine with the given voices and behavior knobs."""
        self._voices = voices
        self._duration_ms = duration_ms
        self._delay_s = delay_s
        self._fail_texts = frozenset(fail_texts or ())
        self.preparing: tuple[str, float] | None = None
        self._lock = threading.Lock()
        self._concurrent = 0
        self.max_concurrent = 0
        self.finished = 0
        self.warmed_up = False

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Write a tiny silent WAV; honour the configured delay and failures."""
        del voice, speed
        with self._lock:
            self._concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self._concurrent)
        try:
            if self._delay_s:
                time.sleep(self._delay_s)
            if text in self._fail_texts:
                msg = f"fake engine refuses to speak {text!r}"
                raise SynthesisError(msg)
            with wave.open(str(out_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\x00\x00" * 24)
            return self._duration_ms
        finally:
            with self._lock:
                self._concurrent -= 1
                self.finished += 1

    def list_voices(self) -> list[str]:
        """Return the configured voice list."""
        return list(self._voices)

    def warmup(self) -> None:
        """Record that warmup happened."""
        self.warmed_up = True

    def preparation(self) -> tuple[str, float] | None:
        """Report whatever ``preparing`` was set to."""
        return self.preparing
