# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Engine adapters backed by separately installed, offline local worker processes."""

from __future__ import annotations

import base64
import json
import os
import select
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any

from aitts.engine import SynthesisError
from aitts.model_catalog import MODELS

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_FRAME_LIMIT = 512 * 1024
_RESPONSE_TIMEOUT = 300


def runtime_environment(root: Path) -> dict[str, str]:
    """Workers import the installed adapter snapshot and perform no network discovery."""
    return {
        **os.environ,
        "PYTHONPATH": str(root / "adapter"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }


class ManagedEngine:
    """One serialized worker; installing another model never mutates this runtime."""

    is_local = True

    def __init__(self, name: str, root: Path) -> None:
        """Retain a published runtime without starting model inference."""
        self.name = name
        self.root = root
        if name == "chatterbox":
            self.supported_speeds = (1.0,)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._buffer = bytearray()
        self._closed = False

    def list_voices(self) -> list[str]:
        """Return the validated setup catalog without spawning a process."""
        return list(MODELS[self.name].voices)

    def _start(self) -> None:
        if self._closed:
            message = "model worker has been closed"
            raise SynthesisError(message)
        if self._process is None:
            self._process = subprocess.Popen(  # noqa: S603 - published runtime and fixed worker arguments
                [
                    str(self.root / "venv/bin/python"),
                    "-m",
                    "aitts.model_worker",
                    "serve",
                    self.name,
                    str(self.root),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=runtime_environment(self.root),
            )

    def _send(self, payload: dict[str, Any]) -> None:
        self._start()
        process = self._process
        if process is None or process.stdin is None:
            message = "model worker is unavailable"
            raise SynthesisError(message)
        try:
            process.stdin.write(json.dumps(payload).encode() + b"\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            message = "model worker stopped; retry model setup"
            raise SynthesisError(message) from exc

    def _receive(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            message = "model worker is unavailable"
            raise SynthesisError(message)
        deadline = time.monotonic() + _RESPONSE_TIMEOUT
        while b"\n" not in self._buffer:
            ready, _, _ = select.select(
                [process.stdout], [], [], max(0.0, deadline - time.monotonic())
            )
            if not ready:
                self.close()
                message = "model worker timed out; retry model setup"
                raise SynthesisError(message)
            block = os.read(process.stdout.fileno(), 65536)
            if not block or len(self._buffer) + len(block) > _FRAME_LIMIT:
                self.close()
                message = "model worker returned an invalid response"
                raise SynthesisError(message)
            self._buffer.extend(block)
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = bytearray(rest)
        try:
            result: object = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            message = "model could not render audio; retry model setup"
            raise SynthesisError(message) from exc
        if not isinstance(result, dict) or result.get("ok") is False:
            message = "model could not render audio; restart the model"
            raise SynthesisError(message)
        return result

    def warmup(self) -> None:
        """Load only the already installed, offline assets."""
        with self._lock:
            self._send({"op": "warmup"})
            if self._receive().get("ok") is not True:
                message = "model could not prepare"
                raise SynthesisError(message)

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Preserve the existing artifact boundary through the private pipe."""
        with self._lock:
            self._send(
                {
                    "op": "synthesize",
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "path": str(out_path),
                }
            )
            reply = self._receive()
            duration = reply.get("duration_ms")
            if reply.get("ok") is not True or type(duration) is not int or duration <= 0:
                message = "model returned invalid audio duration"
                raise SynthesisError(message)
            return duration

    def evidence(self, voice: str) -> dict[str, Any]:
        """Retain actual weight/voice identities and versions from the inference runtime."""
        with self._lock:
            self._send({"op": "evidence", "voice": voice})
            metadata = self._receive().get("metadata")
            if not isinstance(metadata, dict):
                message = "model returned invalid provenance"
                raise SynthesisError(message)
            return metadata

    def restart(self) -> None:
        """Discard a failed worker and prepare its already installed assets again."""
        with self._lock:
            self._stop_worker()
            self._closed = False
        self.warmup()

    def close(self) -> None:
        """Interrupt a stuck inference without waiting on its serialization lock."""
        self._closed = True
        self._stop_worker()

    def _stop_worker(self) -> None:
        process = self._process
        self._process = None
        self._buffer.clear()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
            self._process = None


class ManagedStreamingEngine(ManagedEngine):
    """Keep Kokoro's early PCM delivery across the isolated runtime boundary."""

    def stream_synthesize(self, text: str, voice: str, speed: float) -> Iterator[bytes]:
        """Yield actual producer blocks, never synthetic progress audio."""
        with self._lock:
            self._send({"op": "stream", "text": text, "voice": voice, "speed": speed})
            complete = False
            try:
                while True:
                    reply = self._receive()
                    if reply.get("ok") is True:
                        complete = True
                        return
                    try:
                        pcm = base64.b64decode(reply["pcm"], validate=True)
                    except (KeyError, ValueError, TypeError) as exc:
                        message = "model returned invalid PCM"
                        raise SynthesisError(message) from exc
                    if not pcm or len(pcm) % 2:
                        message = "model returned invalid PCM"
                        raise SynthesisError(message)
                    yield pcm
            finally:
                if not complete:
                    # Retire unread responses so the next clip cannot consume stale PCM.
                    self._stop_worker()


def managed_engine(name: str, root: Path) -> ManagedEngine:
    """Chatterbox remains file-only; Kokoro retains incremental synthesis."""
    adapter = ManagedEngine if name == "chatterbox" else ManagedStreamingEngine
    return adapter(name, root)
