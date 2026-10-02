# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""OpenAI-compatible speech over a direct, loopback-only HTTP connection."""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import math
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from aitts.engine import SynthesisError

if TYPE_CHECKING:
    from pathlib import Path

_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_VALIDATION_BLOCK_FRAMES = 65536


class OpenAIAudioEngine:
    """Render through a local server without DNS, proxies or redirect following.

    The URL names a loopback HTTP(S) server. ``localhost`` is pinned to IPv4
    loopback rather than resolved through DNS. HTTPS verifies the numeric
    destination certificate. Remote endpoints are deliberately unsupported.
    """

    name = "openai-audio"
    is_local = True
    externally_managed = True

    def __init__(
        self,
        url: str,
        model: str,
        default_voice: str,
        *,
        timeout: float = 30,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        """Validate local routing and retain the requested server model and voice."""
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
        ):
            msg = "speech URL must be HTTP(S) loopback without credentials, query or fragment"
            raise ValueError(msg)
        host = "127.0.0.1" if parsed.hostname.lower() == "localhost" else parsed.hostname
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            msg = "speech URL must name localhost or a literal loopback address"
            raise ValueError(msg) from exc
        if not address.is_loopback:
            msg = "speech server must be on loopback; remote text transmission is disabled"
            raise ValueError(msg)
        if not model.strip() or not default_voice.strip():
            msg = "speech model and default voice must not be empty"
            raise ValueError(msg)
        if not math.isfinite(timeout) or timeout <= 0 or max_response_bytes < 1:
            msg = "speech response timeout and byte limit must be positive"
            raise ValueError(msg)
        if parsed.port == 0:
            msg = "speech URL port must be between 1 and 65535"
            raise ValueError(msg)
        self._host = str(address)
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._secure = parsed.scheme == "https"
        path = parsed.path.rstrip("/")
        if path.endswith("/audio/speech"):
            self._path = path
        elif path.endswith("/v1"):
            self._path = path + "/audio/speech"
        else:
            self._path = path + "/v1/audio/speech"
        self._model = model
        self._voice = default_voice
        self._timeout = timeout
        self._max_response_bytes = max_response_bytes

    def list_voices(self) -> list[str]:
        """Return the configured voice; the speech API has no standard voice catalog."""
        return [self._voice]

    def warmup(self) -> None:
        """Prepare no network state; the separately managed server owns its model."""

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """POST one speech request and publish only a complete, playable WAV result."""
        import numpy as np  # noqa: PLC0415 - loaded only by actual audio synthesis
        import soundfile as sf  # noqa: PLC0415 - loaded only by actual audio synthesis

        payload = json.dumps(
            {
                "input": text,
                "voice": voice,
                "model": self._model,
                "speed": speed,
                "response_format": "wav",
            },
            allow_nan=False,
        ).encode("utf-8")
        connection_type = (
            http.client.HTTPSConnection if self._secure else http.client.HTTPConnection
        )
        connection = connection_type(self._host, self._port, timeout=self._timeout)
        try:
            connection.request(
                "POST",
                self._path,
                body=payload,
                headers={"Content-Type": "application/json", "Accept": "audio/wav"},
            )
            with connection.getresponse() as response:
                self._write_response(response, out_path)
            with sf.SoundFile(str(out_path)) as audio:
                if audio.format not in {"WAV", "WAVEX"} or audio.frames <= 0:
                    msg = "local speech endpoint did not return a nonempty WAV"
                    raise SynthesisError(msg)  # noqa: TRY301 - remove the failed artifact
                # Bounded blocks: a byte-limited 8-bit WAV would decode to 4x its size at once.
                for block in audio.blocks(blocksize=_VALIDATION_BLOCK_FRAMES, dtype="float32"):
                    if not np.isfinite(block).all():
                        msg = "local speech endpoint returned non-finite audio samples"
                        raise SynthesisError(msg)  # noqa: TRY301 - remove the failed artifact
                return int(audio.frames * 1000 / audio.samplerate)
        except Exception as exc:
            with contextlib.suppress(OSError):
                out_path.unlink(missing_ok=True)
            if isinstance(exc, SynthesisError):
                raise
            msg = "local speech request failed or returned invalid audio"
            raise SynthesisError(msg) from exc
        finally:
            connection.close()

    def _write_response(self, response: http.client.HTTPResponse, out_path: Path) -> None:
        if response.status != HTTPStatus.OK:
            msg = (
                f"local speech endpoint returned HTTP {response.status}; redirects are not followed"
            )
            raise SynthesisError(msg)
        length = response.getheader("Content-Length")
        if length is not None and not 0 <= int(length) <= self._max_response_bytes:
            msg = "local speech response exceeds the audio byte limit"
            raise SynthesisError(msg)
        total = 0
        with out_path.open("wb") as output:
            while block := response.read(min(65536, self._max_response_bytes - total + 1)):
                total += len(block)
                if total > self._max_response_bytes:
                    msg = "local speech response exceeds the audio byte limit"
                    raise SynthesisError(msg)
                output.write(block)
        if length is not None and total != int(length):
            msg = "local speech response ended before its declared length"
            raise SynthesisError(msg)

    def evidence(self, voice: str) -> dict[str, Any]:
        """Describe local routing without claiming access to the server's model weights."""
        return {
            "backend": self.name,
            "model": self._model,
            "voice": voice,
            "host": self._host,
            "port": self._port,
            "model_identity": "server-managed; weights are not inspectable by this adapter",
        }
