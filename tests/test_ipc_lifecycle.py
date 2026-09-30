# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The IPC shutdown boundary retires dispatch before its owner closes state."""

from __future__ import annotations

import asyncio
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
