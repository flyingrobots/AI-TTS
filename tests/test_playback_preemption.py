# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Preemption contract: nested clips resume their exact source positions."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from aitts.model import Priority, State, Utterance
from aitts.playback import FakeSink
from aitts.store import Store
from tests.test_playback import (
    DelayedReleaseSink,
    make_composite_ready,
    playback_controller,
    settle,
    start,
)

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("Preemption: LIFO resumption at saved chunk/offset, without sink overlap"),
]


def preempting_clip(store: Store, text: str) -> Utterance:
    clip = store.submit(text, voice="v", speed=1.0, priority=Priority.PREEMPT, at_head=True)
    store.transition(clip.id, State.SYNTHESIZING)
    return store.transition(clip.id, State.READY, audio_path=f"/x/{clip.id}.wav", duration_ms=1000)


@pytest.mark.parametrize("ending", ["played", "failed", "skipped"])
async def test_nested_preemption_restores_chunk_and_offset(
    store: Store,
    sink: FakeSink,
    ending: str,
) -> None:
    document = make_composite_ready(store, "document", ("first", "second"))
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    try:
        sink.finish_current()
        await schedule.wait_for_idle_after(schedule.idle_cycles)
        sink.advance_to(375)
        alert = preempting_clip(store, "alert")
        await settle(controller, schedule)
        assert (controller.current_id,) == (alert.id,)
        saved = store.get(document.id)
        assert saved is not None
        assert saved.played_ms == 1375
        sink.advance_to(125)
        nested = preempting_clip(store, "nested alert")
        await settle(controller, schedule)
        assert (controller.current_id,) == (nested.id,)
        if ending == "skipped":
            await controller.skip()
        else:
            if ending == "played":
                sink.finish_current()
            else:
                sink.fail_current("controlled device failure")
            # Watcher runs before the next planning turn; no timing sleeps.
            await schedule.wait_for_idle_after(schedule.idle_cycles)
        await settle(controller, schedule)
        assert (controller.current_id, sink.start_positions[-1]) == (alert.id, 125)
        await controller.skip()
        await settle(controller, schedule)
        segment = controller.current_segment
        assert segment is not None
        assert (controller.current_id, segment.index, sink.start_positions[-1]) == (
            document.id,
            1,
            375,
        )
        assert sink.overlaps == 0
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await controller.skip()


async def test_hold_defers_preemption_and_clear_discards_suspended_clip(
    store: Store,
    sink: FakeSink,
) -> None:
    document = make_composite_ready(store, "document", ("first", "second"))
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    try:
        sink.advance_to(300)
        await controller.pause()
        alert = preempting_clip(store, "alert")
        await settle(controller, schedule)
        assert (controller.current_id,) == (document.id,)
        assert len(sink.started) == 1
        await controller.resume()
        await settle(controller, schedule)
        assert (controller.current_id,) == (alert.id,)
        assert await controller.clear_preempted() == 1
        await controller.skip()
        await settle(controller, schedule)
        assert (controller.current_id,) == (None,)
        saved = store.get(document.id)
        assert saved is not None
        assert (saved.state, saved.played_ms) == (State.SKIPPED, 300)
        assert len(sink.started) == 2
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await controller.skip()


class OneDelayedReleaseSink(DelayedReleaseSink):
    """The test releases the first device handoff; subsequent stops are immediate."""

    release_immediately = False

    def stop(self) -> None:
        if self.release_immediately:
            FakeSink.stop(self)
        else:
            super().stop()


async def test_hold_during_device_handoff_prevents_alert_start(store: Store) -> None:
    sink = OneDelayedReleaseSink()
    document = make_composite_ready(store, "document", ("first", "second"))
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    try:
        sink.advance_to(300)
        alert = preempting_clip(store, "alert")
        controller.notify()
        async with asyncio.timeout(1):
            await sink.stop_requested.wait()
        await controller.pause()
        sink.advance_to(350)  # final accepted block during teardown
        cycle = schedule.idle_cycles
        sink.release_stop()
        await schedule.wait_for_idle_after(cycle)
        assert len(sink.started) == 1
        saved = store.get(document.id)
        assert saved is not None
        assert (saved.state, saved.played_ms) == (State.PAUSED, 350)
        # Resume without adding another delayed handoff to this schedule.
        sink.release_immediately = True
        await controller.resume()
        await settle(controller, schedule)
        assert (controller.current_id,) == (alert.id,)
        await controller.skip()
        await settle(controller, schedule)
        assert (controller.current_id, sink.start_positions[-1]) == (document.id, 350)
        assert sink.overlaps == 0
    finally:
        sink.release_immediately = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await controller.skip()


async def test_restart_keeps_suspended_speech_held_then_resumes_it(store: Store) -> None:
    sink = FakeSink()
    document = make_composite_ready(store, "document", ("first", "second"))
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    sink.advance_to(275)
    alert = preempting_clip(store, "alert")
    await settle(controller, schedule)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # A process crash loses the controller and device; SQLite state survives.
    # Stop the owned test device and let its watcher settle before recovering.
    sink.stop()
    store.recover()
    restored_sink = FakeSink()
    restored, restored_schedule = playback_controller(store, restored_sink, held=True)
    restored_task = await start(restored, restored_schedule)
    try:
        assert restored_sink.started == []
        await restored.resume()
        await settle(restored, restored_schedule)
        assert (restored.current_id,) == (alert.id,)
        await restored.skip()
        await settle(restored, restored_schedule)
        assert (restored.current_id, restored_sink.start_positions[-1]) == (document.id, 275)
    finally:
        restored_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await restored_task
        await restored.skip()


async def test_cancelled_alert_during_handoff_restores_interrupted_document(store: Store) -> None:
    sink = OneDelayedReleaseSink()
    document = make_composite_ready(store, "document", ("first", "second"))
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    try:
        sink.advance_to(300)
        alert = preempting_clip(store, "alert")
        controller.notify()
        async with asyncio.timeout(1):
            await sink.stop_requested.wait()
        store.transition(alert.id, State.CANCELLED)
        cycle = schedule.idle_cycles
        sink.release_stop()
        sink.release_immediately = True
        await schedule.wait_for_idle_after(cycle)
        assert (controller.current_id, sink.start_positions[-1]) == (document.id, 300)
        assert sink.overlaps == 0
    finally:
        sink.release_immediately = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await controller.skip()


async def test_preemption_between_chunks_preserves_completed_progress(
    store: Store,
    sink: FakeSink,
) -> None:
    document = store.submit("document", voice="v", speed=1.0, spoken_segments=("first", "second"))
    first = store.claim_for_synthesis()
    assert first is not None
    store.finish_synthesis(first, audio_path="/x/first.wav", duration_ms=1000)
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    try:
        sink.finish_current()
        await schedule.wait_for_idle_after(schedule.idle_cycles)
        preempting_clip(store, "alert")
        await settle(controller, schedule)
        saved = store.get(document.id)
        assert saved is not None
        assert (saved.state, saved.played_ms) == (State.PAUSED, 1000)
        await controller.skip()
        await settle(controller, schedule)
        second = store.claim_for_synthesis()
        assert second is not None
        store.finish_synthesis(second, audio_path="/x/second.wav", duration_ms=1000)
        await settle(controller, schedule)
        segment = controller.current_segment
        assert segment is not None
        assert (controller.current_id, segment.index, sink.start_positions[-1]) == (
            document.id,
            1,
            0,
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await controller.skip()
