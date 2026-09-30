# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The IPC shutdown boundary retires dispatch before its owner closes state."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aitts.ipc import IPCServer

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("IPCServer.stop retires request handlers before daemon state is closed"),
]


async def test_stop_retires_inflight_dispatch_and_discards_buffered_requests() -> None:
    # No timing inference: stop's return is the contractual quiescence boundary.
    # Retire only if request ownership moves to another calibrated shutdown port.
    entered = asyncio.Event()
    retired = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    class GatedApi:
        async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(payload["op"])
            entered.set()
            try:
                await release.wait()
                return {"ok": True}
            finally:
                retired.set()

    with tempfile.TemporaryDirectory(prefix="aitts-ipc-stop-") as sockets:
        server = IPCServer(Path(sockets) / "d.sock", GatedApi())
        await server.start()
        _reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        try:
            writer.write(b'{"op":"first"}\n{"op":"buffered"}\n')
            await writer.drain()
            await asyncio.wait_for(entered.wait(), 2)
            await server.stop()
            assert retired.is_set(), (
                "stop returned while application dispatch still owned resources"
            )
            assert calls == ["first"], "shutdown dispatched another buffered operation"
        finally:
            release.set()
            await asyncio.wait_for(retired.wait(), 2)
            writer.close()
            await writer.wait_closed()
            await server.stop()


@pytest.mark.oracle("one IPC server owns an endpoint until its shutdown completes")
async def test_second_server_cannot_replace_a_live_endpoint() -> None:
    class IdentityApi:
        def __init__(self, name: str) -> None:
            self.name = name

        async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
            del payload
            return {"ok": True, "owner": self.name}

    with tempfile.TemporaryDirectory(prefix="aitts-owner-") as sockets:
        path = Path(sockets) / "d.sock"
        first = IPCServer(path, IdentityApi("first"))
        second = IPCServer(path, IdentityApi("second"))
        await first.start()
        try:
            with pytest.raises(RuntimeError, match="already owned"):
                await second.start()
            await second.stop()
            reader, writer = await asyncio.open_unix_connection(str(path))
            try:
                writer.write(b'{"op":"identity"}\n')
                await writer.drain()
                assert json.loads(await reader.readline()) == {"ok": True, "owner": "first"}
            finally:
                writer.close()
                await writer.wait_closed()
            await first.stop()
            await second.start()
            await first.stop()
            reader, writer = await asyncio.open_unix_connection(str(path))
            try:
                writer.write(b'{"op":"identity"}\n')
                await writer.drain()
                assert json.loads(await reader.readline()) == {"ok": True, "owner": "second"}
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await second.stop()
            await first.stop()


@pytest.mark.oracle("a live legacy socket without a lease is never replaced or removed")
async def test_existing_unleased_listener_survives_failed_start() -> None:
    import socket  # noqa: PLC0415

    class UnusedApi:
        async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
            return payload

    with tempfile.TemporaryDirectory(prefix="aitts-legacy-owner-") as sockets:
        path = Path(sockets) / "d.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as legacy:
            legacy.bind(str(path))
            legacy.listen(4)
            identity = path.stat().st_ino
            contender = IPCServer(path, UnusedApi())
            try:
                with pytest.raises(RuntimeError, match="already owned"):
                    await contender.start()
                await contender.stop()
                assert path.stat().st_ino == identity
            finally:
                await contender.stop()


@pytest.mark.oracle("an abandoned Unix socket remains restartable without deleting regular files")
@pytest.mark.parametrize("stale_socket", [False, True])
async def test_start_distinguishes_stale_socket_from_unrelated_file(*, stale_socket: bool) -> None:
    import socket  # noqa: PLC0415

    class EchoApi:
        async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
            return payload

    with tempfile.TemporaryDirectory(prefix="aitts-stale-") as sockets:
        path = Path(sockets) / "d.sock"
        if stale_socket:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as abandoned:
                abandoned.bind(str(path))
        else:
            path.write_text("unrelated file")
        server = IPCServer(path, EchoApi())
        try:
            if not stale_socket:
                with pytest.raises(RuntimeError, match="non-socket"):
                    await server.start()
                assert path.read_text() == "unrelated file"
            else:
                await server.start()
                reader, writer = await asyncio.open_unix_connection(str(path))
                try:
                    writer.write(b'{"op":"echo"}\n')
                    await writer.drain()
                    assert json.loads(await reader.readline()) == {"op": "echo"}
                finally:
                    writer.close()
                    await writer.wait_closed()
        finally:
            await server.stop()
