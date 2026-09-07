# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Stepping between the chunks of one document (architecture §2, §7).

A long submission is one queue entry with a nested queue, so Skip — which
abandons the whole entry — is too blunt a control for it. Within a document
the listener wants to move a chunk at a time, forwards over something they
already understood and backwards over something they missed.
"""

from __future__ import annotations

import asyncio

import pytest

from aitts.model import State
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from tests.conftest import wait_for
from tests.test_playback import DeterministicPlaybackSchedule, make_composite_ready, make_ready

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "nested per-document clip queues in architecture section 2 and listener-owned "
        "transport in section 7"
    ),
]

SEGMENTS = ("first chunk", "second chunk", "third chunk")


def segment_states(store: Store, utt_id: str) -> list[State]:
    """Every segment state of ``utt_id``, in order."""
    return [segment.state for segment in store.segments(utt_id)]


async def playing_document(
    store: Store, sink: FakeSink
) -> tuple[PlaybackController, asyncio.Task[None], str]:
    """Start a three-chunk document and wait until its first chunk holds the device."""
    parent = make_composite_ready(store, " ".join(SEGMENTS), SEGMENTS)
    ctl = PlaybackController(store, sink, DeterministicPlaybackSchedule())
    task = asyncio.get_running_loop().create_task(ctl.run())
    await wait_for(lambda: ctl.current_segment is not None)
    return ctl, task, parent.id


# -- forwards -------------------------------------------------------------


async def test_next_chunk_abandons_only_the_current_chunk(store: Store, sink: FakeSink) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        sink.advance_to(250)

        assert await ctl.next_segment() is True

        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 1)
        assert segment_states(store, utt_id) == [State.SKIPPED, State.PLAYING, State.READY]
        # The document itself keeps playing; only a chunk was given up.
        parent = store.get(utt_id)
        assert parent is not None
        assert parent.state is State.PLAYING
    finally:
        task.cancel()


async def test_next_chunk_records_where_the_chunk_was_abandoned(
    store: Store, sink: FakeSink
) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        sink.advance_to(400)

        await ctl.next_segment()

        abandoned = store.get_segment(utt_id, 0)
        assert abandoned is not None
        assert abandoned.played_ms == 400
    finally:
        task.cancel()


async def test_next_chunk_on_the_last_chunk_does_nothing(store: Store, sink: FakeSink) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        await ctl.next_segment()
        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 1)
        await ctl.next_segment()
        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 2)

        # Abandoning the whole entry is Skip's job, not this control's.
        assert await ctl.next_segment() is False
        assert ctl.current_segment is not None
        assert ctl.current_segment.index == 2
        parent = store.get(utt_id)
        assert parent is not None
        assert parent.state is State.PLAYING
    finally:
        task.cancel()


# -- backwards ------------------------------------------------------------


async def test_previous_chunk_replays_the_chunk_before(store: Store, sink: FakeSink) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        await ctl.next_segment()
        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 1)

        assert await ctl.previous_segment() is True

        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 0)
        # The chunk it went back to plays from its start, not from where it stopped.
        assert sink.start_positions[-1] == 0
        assert segment_states(store, utt_id) == [State.PLAYING, State.READY, State.READY]
    finally:
        task.cancel()


async def test_previous_chunk_on_the_first_chunk_does_nothing(store: Store, sink: FakeSink) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        assert await ctl.previous_segment() is False
        assert ctl.current_segment is not None
        assert ctl.current_segment.index == 0
        assert segment_states(store, utt_id) == [State.PLAYING, State.READY, State.READY]
    finally:
        task.cancel()


async def test_previous_chunk_rewinds_the_documents_elapsed_time(
    store: Store, sink: FakeSink
) -> None:
    parent = make_composite_ready(store, " ".join(SEGMENTS), SEGMENTS)
    ctl = PlaybackController(store, sink, DeterministicPlaybackSchedule())
    task = asyncio.get_running_loop().create_task(ctl.run())
    try:
        # Hear the first chunk out, so there is played time to rewind past.
        await wait_for(lambda: ctl.current_segment is not None)
        sink.advance_to(1000)
        sink.finish_current()
        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 1)
        assert ctl.current_position_ms() == 1000

        await ctl.previous_segment()

        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 0)
        # The playhead is back at the top of the document, and the chunk it
        # returned to is owed again rather than counted as heard.
        assert ctl.current_position_ms() == 0
        rewound = store.get(parent.id)
        assert rewound is not None
        assert rewound.played_ms == 0
    finally:
        task.cancel()


async def test_stepping_back_over_an_abandoned_chunk_does_not_credit_it_as_heard(
    store: Store, sink: FakeSink
) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        await ctl.next_segment()
        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 1)

        await ctl.previous_segment()
        await wait_for(lambda: ctl.current_segment is not None and ctl.current_segment.index == 0)

        # Elapsed time counts what was actually played, and an abandoned chunk
        # was not. The progress-bar consequence of that predates chunk stepping
        # and is logged in the code smell journal rather than changed here.
        assert ctl.current_position_ms() == 0
        parent = store.get(utt_id)
        assert parent is not None
        assert parent.played_ms == 0
    finally:
        task.cancel()


# -- what these controls refuse to do -------------------------------------


async def test_chunk_navigation_does_nothing_to_a_single_clip(store: Store, sink: FakeSink) -> None:
    make_ready(store, "one short thing")
    ctl = PlaybackController(store, sink, DeterministicPlaybackSchedule())
    task = asyncio.get_running_loop().create_task(ctl.run())
    try:
        await wait_for(lambda: ctl.current_id is not None)

        # An entry with no nested queue has no chunks to step between.
        assert await ctl.next_segment() is False
        assert await ctl.previous_segment() is False
    finally:
        task.cancel()


async def test_chunk_navigation_is_refused_while_playback_is_held(
    store: Store, sink: FakeSink
) -> None:
    ctl, task, utt_id = await playing_document(store, sink)
    try:
        await ctl.pause()

        # Matches Restart: the transport does not move under a hold.
        assert await ctl.next_segment() is False
        assert await ctl.previous_segment() is False
        assert segment_states(store, utt_id)[0] is State.PAUSED
    finally:
        task.cancel()
