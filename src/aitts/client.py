# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A synchronous client for the daemon's socket protocol.

A caller that must know an utterance was actually spoken subscribes and waits
for its terminal state; it does not read an exit code (architecture.md §5).
:meth:`Client.wait_for_terminal` is that pattern, packaged.
"""

from __future__ import annotations

import socket
import time
from typing import TYPE_CHECKING, Any

from aitts.adapters.jsonl import JsonlDecodeError, decode_json_object, encode_json_object
from aitts.model import TERMINAL, State

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class DaemonUnreachableError(Exception):
    """The daemon is not running, not listening, or not answering."""


class DaemonError(Exception):
    """The daemon answered with a typed error."""

    def __init__(self, error_type: str, message: str) -> None:
        """Wrap a wire error of ``error_type``."""
        super().__init__(message)
        self.error_type = error_type


# How long one read waits before checking the overall deadline. Short enough
# that a deadline is honoured promptly, long enough not to spin.
_EVENT_POLL_SECONDS = 0.5


class Client:
    """Talks NDJSON to the daemon over its Unix socket."""

    def __init__(self, socket_path: Path, *, timeout: float = 10.0) -> None:
        """Create a client for the daemon at ``socket_path``."""
        self._socket_path = socket_path
        self._timeout = timeout

    def _connect(self) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        try:
            sock.connect(str(self._socket_path))
        except OSError as exc:
            sock.close()
            msg = f"cannot reach the daemon at {self._socket_path}: {exc}"
            raise DaemonUnreachableError(msg) from exc
        return sock

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one request and return the daemon's response.

        Raises :class:`DaemonError` when the daemon answers ``ok: false`` and
        :class:`DaemonUnreachableError` when it does not answer at all.
        """
        sock = self._connect()
        try:
            sock.sendall(encode_json_object(payload))
            line = self._read_line(sock)
        finally:
            sock.close()
        response = self._decode_line(line)
        if not response.get("ok", False):
            error = response.get("error") or {}
            raise DaemonError(str(error.get("type", "internal")), str(error.get("message", "")))
        return response

    @staticmethod
    def _read_line(sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(65536)
            except TimeoutError as exc:
                msg = "timed out waiting for the daemon's response"
                raise DaemonUnreachableError(msg) from exc
            if not chunk:
                msg = "the daemon closed the connection without answering"
                raise DaemonUnreachableError(msg)
            chunks.append(chunk)
            if b"\n" in chunk:
                return b"".join(chunks).split(b"\n", 1)[0]

    def events(
        self,
        *,
        timeout: float | None = None,
        until: float | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Subscribe and yield state-change events until the connection closes.

        ``timeout`` bounds the wait for each individual event. ``until`` is an
        optional overall monotonic deadline: while it has not passed, a read
        that times out is a quiet daemon rather than an absent one, so the
        wait resumes instead of failing.
        """
        sock = self._connect()
        sock.settimeout(timeout)
        try:
            sock.sendall(encode_json_object({"op": "subscribe"}))
            line, buffer = self._read_buffered_line(sock, b"")
            ack = self._decode_line(line)
            if not ack.get("ok", False):  # pragma: no cover - subscribe cannot fail
                msg = "subscription refused"
                raise DaemonUnreachableError(msg)
            while True:
                try:
                    line, buffer = self._read_buffered_line(sock, buffer)
                except TimeoutError:
                    if until is not None and time.monotonic() < until:
                        # Nothing has happened yet, which is not a failure.
                        continue
                    if until is None:
                        raise
                    return
                yield self._decode_line(line)
        except TimeoutError as exc:
            msg = "timed out waiting for an event"
            raise DaemonUnreachableError(msg) from exc
        finally:
            sock.close()

    @staticmethod
    def _read_buffered_line(sock: socket.socket, buffer: bytes) -> tuple[bytes, bytes]:
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                msg = "the daemon closed the event stream"
                raise DaemonUnreachableError(msg)
            buffer += chunk
        line, _, rest = buffer.partition(b"\n")
        return line, rest

    @staticmethod
    def _decode_line(line: bytes) -> dict[str, Any]:
        try:
            return decode_json_object(line)
        except JsonlDecodeError as exc:
            msg = f"daemon returned invalid JSONL: {exc}"
            raise DaemonUnreachableError(msg) from exc

    def wait_for_terminal(self, utt_id: str, *, timeout: float | None = None) -> str:
        """Block until ``utt_id`` reaches a terminal state; return that state.

        Subscribes before checking current state, so a transition between the
        check and the subscription cannot be missed.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        # Poll in short reads rather than handing the overall deadline to the
        # socket. They are different questions: "has an event arrived yet" and
        # "has this utterance run out of time". Conflating them reported a
        # healthy daemon as unreachable whenever synthesis was simply slower
        # than the deadline — a cold model, a long document, a loaded machine.
        events = self.events(
            timeout=_EVENT_POLL_SECONDS if timeout is None else min(_EVENT_POLL_SECONDS, timeout),
            until=deadline,
        )
        try:
            current = self.request({"op": "get", "id": utt_id})
            state = State(current["item"]["state"])
            if state in TERMINAL:
                return state.value
            for event in events:
                if deadline is not None and time.monotonic() > deadline:
                    msg = f"utterance {utt_id} did not finish within {timeout}s"
                    raise DaemonUnreachableError(msg)
                if event.get("id") == utt_id and State(event["to"]) in TERMINAL:
                    return str(event["to"])
        finally:
            events.close()
        if deadline is not None:
            msg = f"utterance {utt_id} did not finish within {timeout}s"
            raise DaemonUnreachableError(msg)
        msg = "the daemon closed the event stream"  # pragma: no cover
        raise DaemonUnreachableError(msg)  # pragma: no cover
