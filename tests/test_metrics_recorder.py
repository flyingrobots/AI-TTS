# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The two waits architecture section 2 distinguishes, measured separately."""

from __future__ import annotations

import pytest

from aitts.application.metrics import MAX_SAMPLES, MetricsRecorder, summarise
from aitts.model import Priority, Sensitivity, State, Utterance

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the parallel-synthesis, serial-playback split in architecture section 2"),
]


class FakeClock:
    """A clock a test advances explicitly."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def utterance(utt_id: str, state: State, *, error: str | None = None) -> Utterance:
    return Utterance(
        id=utt_id,
        text="hello",
        voice="bm_daniel",
        speed=1.0,
        sensitivity=Sensitivity.CONFIDENTIAL,
        priority=Priority.NORMAL,
        state=state,
        order_key=0.0,
        submitted_at=0.0,
        state_changed_at=0.0,
        error=error,
    )


def test_nothing_measured_is_reported_as_nothing_not_as_zero() -> None:
    snapshot = MetricsRecorder().snapshot()

    # A caller has to tell "no clip has been spoken" from "it was instant".
    assert snapshot["synthesis_wait_ms"] is None
    assert snapshot["playback_wait_ms"] is None
    assert snapshot["playback_failures"] == 0


def test_the_synthesis_wait_and_the_queue_wait_are_measured_separately() -> None:
    clock = FakeClock()
    recorder = MetricsRecorder(now=clock)

    recorder.observe(utterance("utt_a", State.QUEUED))
    clock.advance(0.2)
    recorder.observe(utterance("utt_a", State.SYNTHESIZING))
    clock.advance(0.3)
    recorder.observe(utterance("utt_a", State.READY))
    clock.advance(1.0)
    recorder.observe(utterance("utt_a", State.PLAYING))

    snapshot = recorder.snapshot()
    # Half a second of synthesis, then a second waiting for the device. One
    # number for both would hide which of the two queues was the cost.
    assert snapshot["synthesis_wait_ms"] == {"count": 1, "p50": 500.0, "p95": 500.0, "max": 500.0}
    assert snapshot["synthesis_duration_ms"] == {
        "count": 1,
        "p50": 300.0,
        "p95": 300.0,
        "max": 300.0,
    }
    assert snapshot["playback_wait_ms"] == {
        "count": 1,
        "p50": 1000.0,
        "p95": 1000.0,
        "max": 1000.0,
    }


def test_a_device_failure_is_counted_and_a_cancellation_is_not() -> None:
    recorder = MetricsRecorder()

    recorder.observe(utterance("utt_a", State.FAILED, error="playback device error: gone"))
    recorder.observe(utterance("utt_b", State.FAILED, error="synthesis failed: engine"))
    recorder.observe(utterance("utt_c", State.CANCELLED))

    # These are all terminal and mean completely different things on call.
    assert recorder.playback_failures == 1


def test_marks_are_dropped_once_an_utterance_settles() -> None:
    recorder = MetricsRecorder()

    recorder.observe(utterance("utt_a", State.QUEUED))
    assert recorder.tracked == 1
    recorder.observe(utterance("utt_a", State.PLAYED))

    # A daemon that runs for a week must not keep a row per clip it ever spoke.
    assert recorder.tracked == 0


def test_samples_are_bounded() -> None:
    clock = FakeClock()
    recorder = MetricsRecorder(now=clock)

    for index in range(MAX_SAMPLES * 2):
        recorder.observe(utterance(f"utt_{index}", State.QUEUED))
        clock.advance(0.001)
        recorder.observe(utterance(f"utt_{index}", State.READY))
        recorder.observe(utterance(f"utt_{index}", State.PLAYED))

    summary = recorder.snapshot()["synthesis_wait_ms"]
    assert isinstance(summary, dict)
    assert summary["count"] == MAX_SAMPLES


def test_percentiles_interpolate_rather_than_pick_the_nearest() -> None:
    summary = summarise([10.0, 20.0, 30.0, 40.0])

    assert summary is not None
    assert summary["p50"] == 25.0
    assert summary["max"] == 40.0
