# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Playback controller: strictly serial, in submission order, user-owned (architecture §2, §7)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from aitts.application.playback_schedule import PlaybackCheckpoint
from aitts.model import State, Utterance
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "serialized playback and transport contracts in architecture sections 2 and 7"
    ),
]


def make_ready(store: Store, text: str) -> Utterance:
    utt = store.submit(text, voice="v", speed=1.0)
    store.transition(utt.id, State.SYNTHESIZING)
    return store.transition(utt.id, State.READY, audio_path=f"/x/{utt.id}.wav", duration_ms=1000)


def state_of(store: Store, utt_id: str) -> State:
    got = store.get(utt_id)
    assert got is not None
    return got.state


def sink_paused(sink: FakeSink) -> bool:
    # Read through a call so mypy does not narrow the attribute across mutations.
    return sink.paused


class DeterministicPlaybackSchedule:
    """Condition-driven playback scheduler with optional one-shot gates."""

    def __init__(self, *, gate_sink_result: bool = False) -> None:
        self.idle_cycles = 0
        self._idle_changed = asyncio.Condition()
        self._block_next_plan = False
        self.plan_blocked = asyncio.Event()
        self.release_plan = asyncio.Event()
        self._gate_sink_result = gate_sink_result
        self.sink_result_reached = asyncio.Event()
        self.release_sink_result = asyncio.Event()

    async def checkpoint(self, point: PlaybackCheckpoint) -> None:
        if point is PlaybackCheckpoint.BEFORE_PLAN:
            if self._block_next_plan:
                self._block_next_plan = False
                self.plan_blocked.set()
                await self.release_plan.wait()
            return
        if point is PlaybackCheckpoint.PLAN_IDLE:
            async with self._idle_changed:
                self.idle_cycles += 1
                self._idle_changed.notify_all()
            return
        if self._gate_sink_result:
            self.sink_result_reached.set()
            await self.release_sink_result.wait()

    async def wait_for_idle_after(self, cycle: int) -> None:
        async with asyncio.timeout(1.0):
            async with self._idle_changed:
                await self._idle_changed.wait_for(lambda: self.idle_cycles > cycle)

    def block_next_plan(self) -> None:
        self._block_next_plan = True


@dataclass(frozen=True, slots=True)
class InterleavingCase:
    terminal_first: bool
    device_failure: bool
    expected_state: State
    expected_error: str | None


def playback_controller(
    store: Store,
    sink: FakeSink,
    *,
    held: bool = False,
    schedule: DeterministicPlaybackSchedule | None = None,
) -> tuple[PlaybackController, DeterministicPlaybackSchedule]:
    active_schedule = schedule or DeterministicPlaybackSchedule()
    return (
        PlaybackController(store, sink, active_schedule, held=held),
        active_schedule,
    )


async def start(
    controller: PlaybackController,
    schedule: DeterministicPlaybackSchedule,
) -> asyncio.Task[None]:
    idle_before = schedule.idle_cycles
    task = asyncio.create_task(controller.run())
    await schedule.wait_for_idle_after(idle_before)
    return task


async def settle(
    controller: PlaybackController,
    schedule: DeterministicPlaybackSchedule,
) -> None:
    idle_before = schedule.idle_cycles
    controller.notify()
    await schedule.wait_for_idle_after(idle_before)


async def test_plays_serially_in_submission_order(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    sink.finish_current()
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    assert state_of(store, a.id) is State.PLAYED
    sink.finish_current()
    await wait_for(lambda: state_of(store, b.id) is State.PLAYED)
    assert [p.name for p in sink.started] == [f"{a.id}.wav", f"{b.id}.wav"]
    assert sink.overlaps == 0
    task.cancel()


async def test_holds_order_when_head_is_not_ready(store: Store, sink: FakeSink) -> None:
    a = store.submit("a", voice="v", speed=1.0)  # still queued
    make_ready(store, "b")
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    assert sink.started == []  # b must wait: presentation order is submission order
    store.transition(a.id, State.SYNTHESIZING)
    store.transition(a.id, State.READY, audio_path=f"/x/{a.id}.wav", duration_ms=1)
    controller.notify()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    task.cancel()


async def test_skip_records_position_and_advances(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    sink.advance_to(700)
    await controller.skip()
    got = store.get(a.id)
    assert got is not None
    assert got.state is State.SKIPPED
    assert got.played_ms == 700
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    task.cancel()


async def test_device_failure_marks_current_failed_and_advances(store: Store) -> None:
    sink = FakeSink()
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)

    sink.fail_current("default output unavailable")

    await wait_for(lambda: state_of(store, a.id) is State.FAILED)
    failed = store.get(a.id)
    assert failed is not None
    assert failed.error == "playback device error: default output unavailable"
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    assert sink.overlaps == 0
    task.cancel()


async def test_natural_end_racing_pause_is_still_recorded_as_played(
    store: Store, sink: FakeSink
) -> None:
    controller, schedule = playback_controller(store, sink)
    utterance = make_ready(store, "almost finished")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, utterance.id) is State.PLAYING)

    await controller.pause()
    sink.finish_current()

    await wait_for(lambda: state_of(store, utterance.id) is State.PLAYED)
    assert controller.current_id is None
    task.cancel()


@pytest.mark.parametrize(
    "case",
    [
        InterleavingCase(
            terminal_first=False,
            device_failure=False,
            expected_state=State.PLAYED,
            expected_error=None,
        ),
        InterleavingCase(
            terminal_first=True,
            device_failure=False,
            expected_state=State.PLAYED,
            expected_error=None,
        ),
        InterleavingCase(
            terminal_first=False,
            device_failure=True,
            expected_state=State.FAILED,
            expected_error="playback device error: seeded device failure",
        ),
        InterleavingCase(
            terminal_first=True,
            device_failure=True,
            expected_state=State.FAILED,
            expected_error="playback device error: seeded device failure",
        ),
    ],
    ids=[
        "natural_pause_first",
        "natural_terminal_first",
        "failure_pause_first",
        "failure_terminal_first",
    ],
)
async def test_pause_and_sink_result_interleavings_hold_the_next_clip(
    store: Store,
    sink: FakeSink,
    case: InterleavingCase,
) -> None:
    schedule = DeterministicPlaybackSchedule(gate_sink_result=True)
    controller, schedule = playback_controller(store, sink, schedule=schedule)
    current = make_ready(store, "current")
    following = make_ready(store, "following")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, current.id) is State.PLAYING)
    if case.terminal_first:
        schedule.block_next_plan()

    if case.device_failure:
        sink.fail_current("seeded device failure")
    else:
        sink.finish_current()
    async with asyncio.timeout(1.0):
        await schedule.sink_result_reached.wait()

    idle_before = schedule.idle_cycles
    if case.terminal_first:
        schedule.release_sink_result.set()
        await wait_for(lambda: state_of(store, current.id) is case.expected_state)
        async with asyncio.timeout(1.0):
            await schedule.plan_blocked.wait()
        await controller.pause()
        schedule.release_plan.set()
    else:
        await controller.pause()
        schedule.release_sink_result.set()

    await wait_for(lambda: state_of(store, current.id) is case.expected_state)
    await schedule.wait_for_idle_after(idle_before)
    current_after = store.get(current.id)
    task_running = not task.done()
    task.cancel()

    assert {
        "current_state": None if current_after is None else current_after.state,
        "current_error": None if current_after is None else current_after.error,
        "following_state": state_of(store, following.id),
        "held": controller.held,
        "current_id": controller.current_id,
        "started": tuple(path.name for path in sink.started),
        "overlaps": sink.overlaps,
        "controller_running": task_running,
    } == {
        "current_state": case.expected_state,
        "current_error": case.expected_error,
        "following_state": State.READY,
        "held": True,
        "current_id": None,
        "started": (f"{current.id}.wav",),
        "overlaps": 0,
        "controller_running": True,
    }


async def test_pause_and_resume(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    await controller.pause()
    assert state_of(store, a.id) is State.PAUSED
    assert sink_paused(sink)
    await controller.resume()
    assert state_of(store, a.id) is State.PLAYING
    assert not sink_paused(sink)
    task.cancel()


async def test_skip_while_paused_does_not_release_global_hold(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    await controller.pause()
    await controller.skip()
    await settle(controller, schedule)
    assert state_of(store, a.id) is State.SKIPPED
    assert state_of(store, b.id) is State.READY
    assert controller.held
    assert sink.started == [Path(a.audio_path or "")]
    await controller.resume()
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    task.cancel()


async def test_terminal_head_is_passed_over(store: Store, sink: FakeSink) -> None:
    a = store.submit("a", voice="v", speed=1.0)
    store.transition(a.id, State.SYNTHESIZING)
    store.transition(a.id, State.FAILED, error="boom")
    b = make_ready(store, "b")
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    task.cancel()


async def test_held_controller_starts_nothing_until_resume(store: Store, sink: FakeSink) -> None:
    a = make_ready(store, "a")
    controller, schedule = playback_controller(store, sink, held=True)
    task = await start(controller, schedule)
    assert sink.started == []
    await controller.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    task.cancel()


async def test_pause_while_idle_holds_future_queue_until_resume(
    store: Store, sink: FakeSink
) -> None:
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    await controller.pause()
    a = make_ready(store, "a")
    await settle(controller, schedule)
    assert controller.held
    assert store.get_setting("playback_held", "false") == "true"
    assert state_of(store, a.id) is State.READY
    assert sink.started == []
    await controller.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    assert store.get_setting("playback_held", "true") == "false"
    task.cancel()


async def test_new_controller_restores_idle_global_hold(store: Store, sink: FakeSink) -> None:
    first, _ = playback_controller(store, sink)
    await first.pause()
    a = make_ready(store, "a")
    restored_sink = FakeSink()
    restored, schedule = playback_controller(store, restored_sink)
    task = await start(restored, schedule)
    assert restored.held
    assert state_of(store, a.id) is State.READY
    assert restored_sink.started == []
    await restored.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    task.cancel()


async def test_restart_does_not_release_global_hold(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    await controller.pause()
    await controller.restart_current()
    await settle(controller, schedule)
    assert controller.held
    assert state_of(store, a.id) is State.PAUSED
    assert sink.started == [Path(a.audio_path or "")]
    task.cancel()


async def test_adopts_paused_utterance_after_restart(store: Store, sink: FakeSink) -> None:
    a = make_ready(store, "a")
    store.transition(a.id, State.PLAYING)
    store.transition(a.id, State.PAUSED, played_ms=400)
    controller, schedule = playback_controller(store, sink, held=True)
    assert controller.current_id == a.id
    assert controller.current_position_ms() == 400
    task = await start(controller, schedule)
    assert sink.started == []  # a restored queue never starts speaking on its own
    await controller.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    assert sink.start_positions == [400]  # best-effort resume mid-utterance
    task.cancel()


async def test_restart_current_replays_from_zero(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    sink.advance_to(800)
    await controller.restart_current()
    await wait_for(lambda: len(sink.start_positions) == 2)
    assert sink.start_positions[-1] == 0
    assert state_of(store, a.id) is State.PLAYING
    task.cancel()


async def test_current_position_is_live_while_playing(store: Store, sink: FakeSink) -> None:
    controller, schedule = playback_controller(store, sink)
    a = make_ready(store, "a")
    task = await start(controller, schedule)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    sink.advance_to(650)
    assert controller.current_position_ms() == 650
    task.cancel()


async def test_current_position_uses_stored_ms_when_paused_after_restart(
    store: Store, sink: FakeSink
) -> None:
    a = make_ready(store, "a")
    store.transition(a.id, State.PLAYING)
    store.transition(a.id, State.PAUSED, played_ms=400)
    controller, schedule = playback_controller(store, sink, held=True)
    task = await start(controller, schedule)
    await controller.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    task.cancel()


async def test_current_position_none_when_idle(store: Store, sink: FakeSink) -> None:
    controller, _ = playback_controller(store, sink)
    assert controller.current_position_ms() is None
