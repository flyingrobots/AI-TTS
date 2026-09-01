# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""NDJSON over a Unix domain socket: request/response plus subscription.

A Unix socket cannot be accidentally exposed to a network; a listening port
can (architecture.md §5). The socket is created mode 0600. Every response
carries ``ok``, and failure is a typed error, never an empty response a client
might read as success.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

_MAX_LINE_BYTES = 1024 * 1024

BAD_REQUEST = "bad_request"
NOT_FOUND = "not_found"
ILLEGAL_STATE = "illegal_state"
INTERNAL = "internal"


class ApiError(Exception):
    """A request failure with a wire-visible type."""

    def __init__(self, error_type: str, message: str) -> None:
        """Create an error of ``error_type`` ("bad_request", "not_found", ...)."""
        super().__init__(message)
        self.error_type = error_type


class Api(Protocol):
    """What the IPC server needs from the daemon."""

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle one request; raise :class:`ApiError` for failures."""
        ...


class IPCServer:
    """Serves the protocol on a Unix socket and fans events out to subscribers."""

    def __init__(self, socket_path: Path, api: Api) -> None:
        """Create a server for ``api`` at ``socket_path``."""
        self._socket_path = socket_path
        self._api = api
        self._server: asyncio.Server | None = None
        self._subscribers: set[asyncio.StreamWriter] = set()

    @property
    def socket_path(self) -> Path:
        """Where the socket lives."""
        return self._socket_path

    async def start(self) -> None:
        """Bind the socket (mode 0600) and begin serving."""
        self._socket_path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(
            self._serve_client, path=str(self._socket_path)
        )
        self._socket_path.chmod(0o600)

    async def stop(self) -> None:
        """Stop serving and remove the socket."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for writer in list(self._subscribers):
            writer.close()
        self._subscribers.clear()
        self._socket_path.unlink(missing_ok=True)

    def broadcast(self, event: dict[str, Any]) -> None:
        """Send an event line to every subscriber, dropping dead connections."""
        line = json.dumps(event).encode() + b"\n"
        for writer in list(self._subscribers):
            try:
                writer.write(line)
            except (ConnectionError, RuntimeError):  # pragma: no cover
                self._subscribers.discard(writer)

    async def _serve_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                try:
                    line = await reader.readline()
                except (ConnectionError, asyncio.LimitOverrunError):  # pragma: no cover
                    break
                if not line:
                    break
                if len(line) > _MAX_LINE_BYTES:
                    await self._reply(
                        writer, _error("bad_request", "request line too large")
                    )
                    continue
                await self._handle_line(line, writer)
        finally:
            self._subscribers.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def _handle_line(self, line: bytes, writer: asyncio.StreamWriter) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            await self._reply(writer, _error("bad_request", "not valid JSON"))
            return
        if not isinstance(payload, dict):
            await self._reply(writer, _error("bad_request", "expected a JSON object"))
            return
        if payload.get("op") == "subscribe":
            self._subscribers.add(writer)
            await self._reply(writer, {"ok": True, "subscribed": True})
            return
        try:
            response = await self._api.dispatch(payload)
        except ApiError as exc:
            response = _error(exc.error_type, str(exc))
        except Exception:  # a bad request must never kill the daemon
            log.exception("unhandled error dispatching %r", payload.get("op"))
            response = _error("internal", "internal error; see daemon log")
        await self._reply(writer, response)

    @staticmethod
    async def _reply(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        writer.write(json.dumps(payload).encode() + b"\n")
        with contextlib.suppress(ConnectionError):
            await writer.drain()


def _error(error_type: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"type": error_type, "message": message}}
