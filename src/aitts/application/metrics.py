# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""What the daemon can say about its own responsiveness.

Architecture §2 rests on one claim: the queue, not the engine, governs how
responsive speech feels, because synthesis runs ahead in parallel while
playback stays serial and real-time. That claim was unmeasured, so the two
waits it distinguishes could not be told apart in a running system.

They are separated here on purpose. Submitted-to-Ready is what synthesis
cost, and it is parallel work that can be thrown more workers. Ready-to-
Playing is what the *queue* cost, and no amount of parallelism helps it,
because exactly one utterance may hold the device. A slow first clip means
something different in each case, and one number for both would hide which.

Samples are held in memory and bounded. A daemon's metrics describe the
process that is running, not a durable history; keeping them out of the store
also keeps the hot transition path free of writes.
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aitts.model import Utterance

# Enough to characterise a session without growing without bound.
MAX_SAMPLES = 256


def summarise(samples: Sequence[float]) -> dict[str, float | int] | None:
    """Summarise durations in milliseconds, or ``None`` when there are none.

    A caller must be able to tell "nothing has happened yet" from "it was
    instant"; returning zeros for an empty sample set conflates them.
    """
    if not samples:
        return None
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "p50": round(_percentile(ordered, 0.50), 1),
        "p95": round(_percentile(ordered, 0.95), 1),
        "max": round(ordered[-1], 1),
    }


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


class MetricsRecorder:
    """Accumulate timings from state transitions as they happen."""

    def __init__(self, *, now: object = time.time) -> None:
        """Create a recorder reading the clock through ``now``.

        Wall clock rather than monotonic, because an utterance carries its own
        ``submitted_at`` on the same scale and that is the only record of when
        it was accepted: an utterance is created already Queued, so no
        transition fires to mark the start of its synthesis wait.
        """
        assert callable(now)  # noqa: S101 - internal seam for deterministic tests
        self._now = now
        self._synthesis_wait: deque[float] = deque(maxlen=MAX_SAMPLES)
        self._playback_wait: deque[float] = deque(maxlen=MAX_SAMPLES)
        self._synthesis_duration: deque[float] = deque(maxlen=MAX_SAMPLES)
        # Per-utterance marks, dropped as each one settles so a long-running
        # daemon does not accumulate a row per clip it has ever spoken.
        self._queued_at: dict[str, float] = {}
        self._ready_at: dict[str, float] = {}
        self._synthesis_started_at: dict[str, float] = {}
        self.playback_failures = 0

    def observe(self, utt: Utterance) -> None:
        """Record whatever this transition reveals about timing."""
        from aitts.model import State  # noqa: PLC0415 - avoid an import cycle

        now = float(self._now())
        if utt.state is State.QUEUED:
            self._queued_at.setdefault(utt.id, utt.submitted_at)
        elif utt.state is State.SYNTHESIZING:
            # Seeded from the utterance rather than from a Queued transition,
            # which never fires: submit creates the row already Queued.
            self._queued_at.setdefault(utt.id, utt.submitted_at)
            self._synthesis_started_at.setdefault(utt.id, now)
        elif utt.state is State.READY:
            self._queued_at.setdefault(utt.id, utt.submitted_at)
            self._ready_at[utt.id] = now
            queued = self._queued_at.get(utt.id)
            if queued is not None:
                self._synthesis_wait.append((now - queued) * 1000)
            started = self._synthesis_started_at.pop(utt.id, None)
            if started is not None:
                self._synthesis_duration.append((now - started) * 1000)
        elif utt.state is State.PLAYING:
            ready = self._ready_at.pop(utt.id, None)
            if ready is not None:
                self._playback_wait.append((now - ready) * 1000)
        elif utt.is_terminal:
            # A device failure and a cancellation are both terminal and mean
            # entirely different things to whoever is on call.
            if utt.state is State.FAILED and (utt.error or "").startswith("playback device"):
                self.playback_failures += 1
            self._forget(utt.id)

    def _forget(self, utt_id: str) -> None:
        self._queued_at.pop(utt_id, None)
        self._ready_at.pop(utt_id, None)
        self._synthesis_started_at.pop(utt_id, None)

    @property
    def tracked(self) -> int:
        """How many utterances still have an unsettled mark."""
        return len({*self._queued_at, *self._ready_at, *self._synthesis_started_at})

    def snapshot(self) -> dict[str, object]:
        """Report the timings gathered so far."""
        return {
            "synthesis_wait_ms": summarise(self._synthesis_wait),
            "synthesis_duration_ms": summarise(self._synthesis_duration),
            "playback_wait_ms": summarise(self._playback_wait),
            "playback_failures": self.playback_failures,
        }
