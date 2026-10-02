# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Cancellation-safe asynchronous NDJSON connections for terminal clients."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TYPE_CHECKING, Any

from aitts.adapters.jsonl import decode_json_object, encode_json_object
from aitts.client import DaemonError, DaemonUnreachableError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

# The 1 MiB JSONL limit bounds one request, not a reply. A snapshot aggregates
# the whole plan and up to 50 history texts into one line, so, like the
# synchronous client, this one reads the daemon's replies without a length cap.
_RESPONSE_LINE_LIMIT = sys.maxsize


class AsyncClient:
    """Keep subscription and command sockets independent, using the public wire API."""

    def __init__(self, socket_path: Path, *, timeout: float = 5.0) -> None:
        """Use the configured user socket and bound individual command round trips."""
        self.socket_path = socket_path
        self.timeout = timeout

    @contextlib.asynccontextmanager
    async def _connection(self) -> AsyncIterator[tuple[asyncio.StreamReader, asyncio.StreamWriter]]:
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_unix_connection(
                    str(self.socket_path), limit=_RESPONSE_LINE_LIMIT
                )
            yield reader, writer
        except (OSError, ValueError) as exc:
            msg = f"Cannot communicate with the daemon: {exc}"
            raise DaemonUnreachableError(msg) from exc
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> dict[str, Any]:
        line = await reader.readline()
        if not line.endswith(b"\n"):
            msg = "The daemon closed the connection."
            raise DaemonUnreachableError(msg)
        return decode_json_object(line)

    async def _exchange(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, payload: dict[str, Any]
    ) -> dict[str, Any]:
        async with asyncio.timeout(self.timeout):
            writer.write(encode_json_object(payload))
            await writer.drain()
            response = await self._read(reader)
        if not response.get("ok", False):
            error = response.get("error") or {}
            raise DaemonError(str(error.get("type", "internal")), str(error.get("message", "")))
        return response

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Issue one command without blocking event delivery or replaying mutations."""
        async with self._connection() as (reader, writer):
            return await self._exchange(reader, writer, payload)

    @contextlib.asynccontextmanager
    async def events(
        self, *, playback_progress: bool = False
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """Acknowledge subscription before yielding, then wait through quiet periods."""
        async with self._connection() as (reader, writer):
            payload: dict[str, Any] = {"op": "subscribe"}
            if playback_progress:
                payload["playback_progress"] = True
            await self._exchange(reader, writer, payload)

            async def stream() -> AsyncGenerator[dict[str, Any]]:
                while True:
                    yield await self._read(reader)

            async with contextlib.aclosing(stream()) as events:
                yield events
