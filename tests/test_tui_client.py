# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The terminal adapter obeys the same public socket contract as other clients."""

import asyncio
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from aitts.adapters.jsonl import MAX_JSONL_LINE_BYTES, encode_json_object
from aitts.client import DaemonError, DaemonUnreachableError
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
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


async def test_reply_longer_than_the_request_line_limit_is_delivered(socket_path: Path) -> None:
    # A snapshot aggregates the whole plan and 50 history texts into one line.
    text = "x" * (2 * MAX_JSONL_LINE_BYTES)

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(encode_json_object({"ok": True, "history": [{"text": text}]}))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(serve, str(socket_path))
    async with server:
        reply = await AsyncClient(socket_path).request({"op": "snapshot"})
    assert reply["history"][0]["text"] == text


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


class GatedEngine(FakeEngine):
    """Hold every synthesis until the test releases it, so the only worker stays busy."""

    def __init__(self) -> None:
        super().__init__(voices=["v"])
        self.release = threading.Event()

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        assert self.release.wait(5), "the test never released the gated synthesis"
        return super().synthesize(text, voice, speed, out_path)


@pytest.mark.oracle(
    "docs/design/architecture.md section 5: subscribers observe every queue change, "
    "including an admission that no worker claims yet"
)
@pytest.mark.parametrize("admission", ["submit", "requeue"])
async def test_submission_behind_a_busy_worker_is_published(
    tmp_path: Path, socket_path: Path, admission: str
) -> None:
    engine = GatedEngine()
    daemon = Daemon(
        home=tmp_path, socket_path=socket_path, engine=engine, sink=FakeSink(), workers=1
    )
    await daemon.start()
    try:
        client = AsyncClient(socket_path)
        async with client.events() as events:
            busy = await client.request({"op": "submit", "text": "Occupies the only worker"})
            async with asyncio.timeout(1):
                async for event in events:
                    if event.get("id") == busy["id"] and event.get("to") == "Synthesizing":
                        break
            waiting = await client.request({"op": "submit", "text": "Waits behind the worker"})
            if admission == "requeue":
                # A cancelled clip has no cached audio, so its replay waits for a worker too.
                await client.request({"op": "cancel", "id": waiting["id"]})
                waiting = await client.request({"op": "requeue", "id": waiting["id"]})
            # A later broadcast marks the end of what the admission could have produced.
            await client.request({"op": "settings", "set": {"captions_enabled": True}})
            observed: list[dict[str, object]] = []
            async with asyncio.timeout(1):
                async for event in events:
                    if event.get("event") == "settings_changed":
                        break
                    observed.append(event)
        assert {
            "event": "state_changed",
            "id": waiting["id"],
            "from": None,
            "to": "Queued",
        }.items() <= next((e for e in observed if e.get("id") == waiting["id"]), {}).items(), (
            f"no admission event for the waiting clip: {observed}"
        )
    finally:
        engine.release.set()
        await daemon.stop()
