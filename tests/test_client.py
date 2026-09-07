# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The sync client against a live daemon (features.md §8)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aitts.client import Client, DaemonError, DaemonUnreachableError
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("daemon client protocol in docs/design/architecture.md section 5"),
]


@pytest.fixture
async def daemon(tmp_path: Path) -> Any:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-"))
    d = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(auto_finish_ms=5),
        socket_path=sock_dir / "d.sock",
    )
    await d.start()
    yield d
    await d.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


async def test_submit_and_wait_reaches_played(daemon: Daemon) -> None:
    client = Client(daemon.socket_path)
    response = await asyncio.to_thread(client.request, {"op": "submit", "text": "hi"})
    assert response["ok"] is True
    final = await asyncio.to_thread(client.wait_for_terminal, response["id"], timeout=10.0)
    assert final == "Played"


async def test_wait_returns_immediately_for_already_terminal(daemon: Daemon) -> None:
    client = Client(daemon.socket_path)
    response = await asyncio.to_thread(client.request, {"op": "submit", "text": "hi"})
    await asyncio.to_thread(client.wait_for_terminal, response["id"], timeout=10.0)
    final = await asyncio.to_thread(client.wait_for_terminal, response["id"], timeout=1.0)
    assert final == "Played"


async def test_daemon_error_is_typed(daemon: Daemon) -> None:
    client = Client(daemon.socket_path)
    with pytest.raises(DaemonError) as excinfo:
        await asyncio.to_thread(client.request, {"op": "submit"})
    assert excinfo.value.error_type == "bad_request"


async def test_unreachable_daemon_is_distinguishable(tmp_path: Path) -> None:
    client = Client(tmp_path / "nowhere.sock", timeout=0.5)
    with pytest.raises(DaemonUnreachableError):
        await asyncio.to_thread(client.request, {"op": "status"})


async def test_a_slow_utterance_is_not_reported_as_an_unreachable_daemon(
    tmp_path: Path,
) -> None:
    # A sink that never finishes: the daemon is healthy and the clip is
    # playing, it simply has not reached a terminal state yet.
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-slow-"))
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(),
        workers=1,
        socket_path=sock_dir / "d.sock",
    )
    await daemon.start()
    try:
        client = Client(daemon.socket_path)
        response = await asyncio.to_thread(client.request, {"op": "submit", "text": "hi"})

        with pytest.raises(DaemonUnreachableError) as raised:
            await asyncio.to_thread(client.wait_for_terminal, response["id"], timeout=0.5)

        # The overall deadline was passed to the socket as a per-read timeout,
        # so a quiet period raised "timed out waiting for an event" — which
        # says the daemon is gone. It was reachable throughout, and an agent
        # reading that exit reports a failure that did not happen.
        message = str(raised.value)
        assert "did not finish" in message, message
        assert "waiting for an event" not in message, message

        # And the daemon really was reachable the whole time.
        status = await asyncio.to_thread(client.request, {"op": "status"})
        assert status["ok"] is True
    finally:
        await daemon.stop()
        shutil.rmtree(sock_dir, ignore_errors=True)


async def test_the_event_stream_subscribes_before_it_is_iterated(daemon: Daemon) -> None:
    client = Client(daemon.socket_path)

    stream = await asyncio.to_thread(client.events, timeout=0.5, until=None)
    try:
        # wait_for_terminal documents that it subscribes before reading the
        # current state, so a transition in between cannot be missed. A
        # generator's body does not run until it is first iterated, so the
        # subscription had not happened yet and the promise was not kept.
        await wait_for(lambda: len(daemon._server._subscribers) == 1)
        assert len(daemon._server._subscribers) == 1
    finally:
        stream.close()


async def test_an_utterance_that_finishes_immediately_is_still_observed(
    daemon: Daemon,
) -> None:
    client = Client(daemon.socket_path)

    # The fixture's sink finishes 5ms after playback starts, so this clip can
    # reach a terminal state inside the window between the state check and a
    # late subscription. Missing the event meant waiting out the whole timeout
    # and then reporting failure for speech that had already played.
    for _ in range(6):
        response = await asyncio.to_thread(client.request, {"op": "submit", "text": "hi"})
        final = await asyncio.to_thread(client.wait_for_terminal, response["id"], timeout=5.0)
        assert final == "Played"
