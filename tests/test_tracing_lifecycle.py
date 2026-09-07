# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""One clip is followable end to end in the log (architecture §9 bounds).

The token itself is checked in :mod:`tests.test_diagnostic_tracing`; what
matters here is that the running daemon actually emits it, on the events that
tell an operator where a clip got to, and that two clips in flight at once can
be told apart. A correlation token nothing emits correlates nothing.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.adapters.diagnostic_logging import utterance_trace
from aitts.adapters.playback_schedule import ImmediatePlaybackSchedule
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from tests.conftest import wait_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the bounded-diagnostics policy in architecture section 9"),
]

_TRACE = re.compile(r"trace=(\S+)")


@pytest.fixture
async def daemon(tmp_path: Path) -> AsyncIterator[Daemon]:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-trace-"))
    built = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(auto_finish_ms=5),
        workers=1,
        socket_path=sock_dir / "d.sock",
    )
    await built.start()
    yield built
    await built.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


def traces_in(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every trace token the daemon logged, in order."""
    found = [_TRACE.search(record.getMessage()) for record in caplog.records]
    return [match.group(1) for match in found if match is not None]


async def test_a_clip_is_traceable_from_ready_to_played(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="aitts"):
        reply = await daemon.dispatch({"op": "submit", "text": "hello"})
        await wait_for(lambda: _is(daemon, reply["id"], State.PLAYED))

    # The clip becoming playable, taking the device, and finishing are the
    # three answers to "where did it get to", and all three must carry the
    # same token or the log cannot be joined on it.
    expected = utterance_trace(reply["id"])
    assert traces_in(caplog).count(expected) >= 3


async def test_two_clips_in_flight_are_told_apart(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="aitts"):
        first = await daemon.dispatch({"op": "submit", "text": "one"})
        second = await daemon.dispatch({"op": "submit", "text": "two"})
        await wait_for(lambda: _is(daemon, second["id"], State.PLAYED))

    logged = set(traces_in(caplog))
    # Two clips interleave in the log by design: playback is serial but
    # synthesis is not. Distinguishing them is the point of the token.
    assert utterance_trace(first["id"]) in logged
    assert utterance_trace(second["id"]) in logged


async def test_a_trace_never_carries_the_spoken_text(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    spoken = "moonlight parade"
    with caplog.at_level(logging.INFO, logger="aitts"):
        reply = await daemon.dispatch({"op": "submit", "text": spoken})
        await wait_for(lambda: _is(daemon, reply["id"], State.PLAYED))

    # Tracing is the most tempting place to paste the text being traced, and
    # it is exactly the place architecture section 9 forbids it.
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert traces_in(caplog)
    assert spoken not in logged
    assert "moonlight" not in logged


def _is(daemon: Daemon, utt_id: str, state: State) -> bool:
    found = daemon.store.get(utt_id)
    return found is not None and found.state is state


# -- the events that answer "why is nothing playing" ----------------------


async def test_releasing_a_terminal_document_names_which_one(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    sink = FakeSink()
    segments = ("one", "two")
    parent = store.submit(" ".join(segments), voice="v", speed=1.0, spoken_segments=segments)
    first = store.claim_for_synthesis()
    assert first is not None
    store.finish_synthesis(first, audio_path="/x/0.wav", duration_ms=1000)

    controller = PlaybackController(store, sink, ImmediatePlaybackSchedule())
    task = asyncio.get_running_loop().create_task(controller.run())
    try:
        with caplog.at_level(logging.INFO, logger="aitts"):
            await wait_for(lambda: controller.current_segment is not None)
            sink.advance_to(1000)
            sink.finish_current()
            await wait_for(lambda: not _sink_active(controller))

            # The second chunk fails to synthesize, which fails the document
            # while the controller still owns it and no sink is active.
            second = store.claim_for_synthesis()
            assert second is not None
            store.fail_synthesis(second, "engine unavailable")
            await wait_for(lambda: _settled(store, parent.id))
            controller.notify()
            await wait_for(lambda: controller.current_id is None)
    finally:
        task.cancel()

    # A released document is the difference between "the queue is idle" and
    # "the queue was stuck on this clip". Without the token the line says the
    # first when it means the second.
    released = [
        record.getMessage()
        for record in caplog.records
        if "event=terminal_current_released" in record.getMessage()
    ]
    assert released
    assert all(utterance_trace(parent.id) in message for message in released)


def _sink_active(controller: PlaybackController) -> bool:
    # Read through a call so mypy does not narrow the attribute across waits.
    return controller._sink_active


def _settled(store: Store, utt_id: str) -> bool:
    found = store.get(utt_id)
    return found is not None and found.is_terminal


async def test_an_unrecoverable_document_names_itself(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    sink = FakeSink()
    segments = ("one", "two")
    parent = store.submit(" ".join(segments), voice="v", speed=1.0, spoken_segments=segments)
    for _ in segments:
        work = store.claim_for_synthesis()
        assert work is not None
        store.finish_synthesis(work, audio_path=f"/x/{work.id}.wav", duration_ms=1000)

    controller = PlaybackController(store, sink, ImmediatePlaybackSchedule())
    task = asyncio.get_running_loop().create_task(controller.run())
    try:
        with caplog.at_level(logging.INFO, logger="aitts"):
            await wait_for(lambda: controller.current_segment is not None)
            # The cache is evicted underneath a playing document, so nothing
            # is left to replay when the listener asks to restart it.
            _evict_every_chunk(store, parent.id)
            await controller.restart_current()
            await wait_for(lambda: _settled(store, parent.id))
    finally:
        task.cancel()

    # This is the loudest line the controller can write: a document stopped
    # and will not resume. Naming which one is the difference between a
    # diagnosis and a search.
    unrecoverable = [
        record.getMessage()
        for record in caplog.records
        if "event=document_playback_unrecoverable" in record.getMessage()
    ]
    assert unrecoverable
    assert all(utterance_trace(parent.id) in message for message in unrecoverable)


def _evict_every_chunk(store: Store, utt_id: str) -> None:
    """Drop the cached audio of every chunk, leaving the rows in place."""
    store._db.execute(
        "UPDATE utterance_segments SET audio_path = NULL WHERE utterance_id = ?", (utt_id,)
    )
    store._db.commit()
