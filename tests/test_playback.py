# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Playback controller: strictly serial, in submission order, user-owned (architecture §2, §7)."""

from __future__ import annotations

import asyncio

from aitts.model import State, Utterance
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from tests.conftest import wait_for


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


async def start(controller: PlaybackController) -> asyncio.Task[None]:
    task = asyncio.create_task(controller.run())
    await asyncio.sleep(0)
    return task


async def test_plays_serially_in_submission_order(store: Store, sink: FakeSink) -> None:
    controller = PlaybackController(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller)
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
    controller = PlaybackController(store, sink)
    task = await start(controller)
    await asyncio.sleep(0.05)
    assert sink.started == []  # b must wait: presentation order is submission order
    store.transition(a.id, State.SYNTHESIZING)
    store.transition(a.id, State.READY, audio_path=f"/x/{a.id}.wav", duration_ms=1)
    controller.notify()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    task.cancel()


async def test_skip_records_position_and_advances(store: Store, sink: FakeSink) -> None:
    controller = PlaybackController(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    sink.advance_to(700)
    await controller.skip()
    got = store.get(a.id)
    assert got is not None
    assert got.state is State.SKIPPED
    assert got.played_ms == 700
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    task.cancel()


async def test_pause_and_resume(store: Store, sink: FakeSink) -> None:
    controller = PlaybackController(store, sink)
    a = make_ready(store, "a")
    task = await start(controller)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    await controller.pause()
    assert state_of(store, a.id) is State.PAUSED
    assert sink_paused(sink)
    await controller.resume()
    assert state_of(store, a.id) is State.PLAYING
    assert not sink_paused(sink)
    task.cancel()


async def test_pause_holds_the_queue_not_just_the_utterance(store: Store, sink: FakeSink) -> None:
    controller = PlaybackController(store, sink)
    a = make_ready(store, "a")
    b = make_ready(store, "b")
    task = await start(controller)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    await controller.pause()
    await controller.skip()  # skip from paused: a -> Skipped, playback resumes with b
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    assert state_of(store, a.id) is State.SKIPPED
    task.cancel()


async def test_terminal_head_is_passed_over(store: Store, sink: FakeSink) -> None:
    a = store.submit("a", voice="v", speed=1.0)
    store.transition(a.id, State.SYNTHESIZING)
    store.transition(a.id, State.FAILED, error="boom")
    b = make_ready(store, "b")
    controller = PlaybackController(store, sink)
    task = await start(controller)
    await wait_for(lambda: state_of(store, b.id) is State.PLAYING)
    task.cancel()


async def test_held_controller_starts_nothing_until_resume(store: Store, sink: FakeSink) -> None:
    a = make_ready(store, "a")
    controller = PlaybackController(store, sink, held=True)
    task = await start(controller)
    await asyncio.sleep(0.05)
    assert sink.started == []
    await controller.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    task.cancel()


async def test_adopts_paused_utterance_after_restart(store: Store, sink: FakeSink) -> None:
    a = make_ready(store, "a")
    store.transition(a.id, State.PLAYING)
    store.transition(a.id, State.PAUSED, played_ms=400)
    controller = PlaybackController(store, sink, held=True)
    task = await start(controller)
    await asyncio.sleep(0.02)
    assert sink.started == []  # a restored queue never starts speaking on its own
    await controller.resume()
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    assert sink.start_positions == [400]  # best-effort resume mid-utterance
    task.cancel()


async def test_restart_current_replays_from_zero(store: Store, sink: FakeSink) -> None:
    controller = PlaybackController(store, sink)
    a = make_ready(store, "a")
    task = await start(controller)
    await wait_for(lambda: state_of(store, a.id) is State.PLAYING)
    sink.advance_to(800)
    await controller.restart_current()
    await wait_for(lambda: len(sink.start_positions) == 2)
    assert sink.start_positions[-1] == 0
    assert state_of(store, a.id) is State.PLAYING
    task.cancel()
