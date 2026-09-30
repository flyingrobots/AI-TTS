# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The terminal adapter obeys the same public socket contract as other clients."""

import asyncio
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from aitts.client import DaemonError, DaemonUnreachableError
from aitts.daemon import Daemon
from aitts.tui.client import AsyncClient
from tests.test_ipc import daemon as daemon  # noqa: PLC0414 - expose the shared pytest fixture

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "public NDJSON requests, acknowledged subscriptions and owned socket lifetime"
    ),
]


@pytest.fixture
def socket_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aitts-tui-", dir="/tmp") as folder:
        yield Path(folder) / "s"


async def test_terminal_client_subscribes_before_mutation_and_can_control_daemon(
    daemon: Daemon,
) -> None:
    client = AsyncClient(daemon.socket_path)
    async with client.events() as events:
        paused = await client.request({"op": "pause"})
        assert paused["ok"]
        assert (await client.request({"op": "status"}))["playback_held"] is True
        submitted = await client.request({"op": "submit", "text": "Owned terminal source"})
        async with asyncio.timeout(1):
            async for event in events:
                if event.get("id") == submitted["id"]:
                    assert event["event"] == "state_changed"
                    break
        await client.request({"op": "resume"})
        assert (await client.request({"op": "status"}))["playback_held"] is False
    with pytest.raises(DaemonError) as error:
        await client.request({"op": "not_a_real_operation"})
    assert error.value.error_type == "bad_request"


async def test_subscription_keeps_coalesced_events_and_closes_on_context_exit(
    socket_path: Path,
) -> None:
    eof = asyncio.Event()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            assert await reader.readline() == b'{"op":"subscribe"}\n'
            writer.write(b'{"ok":true}\n{"event":"first"}\n{"event":"second"}\n')
            await writer.drain()
            assert await reader.read() == b""
            eof.set()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(serve, str(socket_path))
    async with server:
        client = AsyncClient(socket_path)
        async with client.events() as events:
            assert await anext(events) == {"event": "first"}
            assert await anext(events) == {"event": "second"}
        await asyncio.wait_for(eof.wait(), 1)


@pytest.mark.parametrize("response", [b"", b"not JSON\n", b'{"ok":true}'])
async def test_broken_reply_is_a_transport_error(socket_path: Path, response: bytes) -> None:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(serve, str(socket_path))
    async with server:
        with pytest.raises(DaemonUnreachableError):
            await AsyncClient(socket_path).request({"op": "status"})


async def test_progress_is_opt_in_and_idle_meter_is_silent(daemon: Daemon) -> None:
    client = AsyncClient(daemon.socket_path)
    async with client.events() as ordinary, client.events(playback_progress=True) as measured:
        async with asyncio.timeout(1):
            progress = await anext(measured)
        assert progress == {
            "event": "playback_progress",
            "playback_held": False,
            "id": None,
            "position_ms": None,
            "audio_peak": 0.0,
        }
        clip = await client.request({"op": "submit", "text": "Owned opt-in event test"})
        async with asyncio.timeout(1):
            event = await anext(ordinary)
        assert event["event"] == "state_changed"
        assert event["id"] == clip["id"]
