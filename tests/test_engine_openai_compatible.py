# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Local speech HTTP exchange, bounded WAV artifacts and fail-closed destinations."""

import contextlib
import io
import json
import socket
import threading
import wave
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any

import pytest

from aitts.engine import SynthesisError
from aitts.engines.openai_compatible import OpenAIAudioEngine

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("PROMPTS #4: loopback-only speech POST, exact request, complete valid WAV"),
]


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        writer.writeframes(b"\x00\x20" * 2400)
    return output.getvalue()


class LoopbackHTTPServer(HTTPServer):
    def server_bind(self) -> None:
        # HTTPServer.server_bind calls getfqdn: a fixture must not consult ambient DNS.
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


@contextlib.contextmanager
def local_server(
    body: bytes,
    *,
    status: int = 200,
    location: str | None = None,
    content_length: bool = True,
    declared_extra: int = 0,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "payload": payload})
            self.send_response(status)
            self.send_header("Content-Type", "audio/wav")
            if content_length:
                self.send_header("Content-Length", str(len(body) + declared_extra))
            if location is not None:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib API
            del format, args

    with LoopbackHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join(timeout=1)


def test_local_speech_request_preserves_arguments_and_wav(tmp_path: Path) -> None:
    body = wav_bytes()
    with local_server(body) as (url, requests):
        engine = OpenAIAudioEngine(url + "/v1", "local-model", "local-voice")
        engine.warmup()
        output = tmp_path / "spoken.wav"
        duration = engine.synthesize("Owned private text", "local-voice", 1.25, output)
    assert engine.is_local is True
    assert engine.list_voices() == ["local-voice"]
    assert requests == [
        {
            "path": "/v1/audio/speech",
            "payload": {
                "input": "Owned private text",
                "voice": "local-voice",
                "model": "local-model",
                "speed": 1.25,
                "response_format": "wav",
            },
        }
    ]
    assert output.read_bytes() == body
    assert duration == 100


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://192.168.1.2/v1",
        "http://localhost.example.com",
        "http://user:secret@127.0.0.1",
        "file:///private.wav",
        "http://127.0.0.1/?token=x",
        "http://127.0.0.1/#fragment",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:0",
        "http://0.0.0.0",
    ],
)
def test_adapter_rejects_nonloopback_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError, match=r"speech|Port out of range"):
        OpenAIAudioEngine(url, "model", "voice")


@pytest.mark.parametrize(
    "failure",
    [
        "bad_audio",
        "empty_audio",
        "too_large",
        "http_error",
        "truncated",
        "oversized_unframed",
    ],
)
def test_failed_response_never_leaves_a_usable_artifact(tmp_path: Path, failure: str) -> None:
    body = {"bad_audio": b"invalid audio", "empty_audio": b""}.get(failure, wav_bytes())
    status = 503 if failure == "http_error" else 200
    with local_server(
        body,
        status=status,
        content_length=failure != "oversized_unframed",
        declared_extra=100 if failure == "truncated" else 0,
    ) as (url, requests):
        engine = OpenAIAudioEngine(
            url,
            "model",
            "voice",
            max_response_bytes=100 if failure in {"too_large", "oversized_unframed"} else 10000,
        )
        output = tmp_path / "candidate.wav"
        with pytest.raises(SynthesisError):
            engine.synthesize("Owned private text", "voice", 1, output)
        assert len(requests) == 1
        assert not output.exists()


@pytest.mark.parametrize("sample", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_float_samples_never_publish_an_artifact(tmp_path: Path, sample: float) -> None:
    import numpy as np  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    samples = np.full(2400, 0.25, dtype=np.float32)
    samples[1200] = sample
    encoded = io.BytesIO()
    sf.write(encoded, samples, 24000, format="WAV", subtype="FLOAT")
    with local_server(encoded.getvalue()) as (url, requests):
        engine = OpenAIAudioEngine(url, "model", "voice")
        output = tmp_path / "candidate.wav"
        with pytest.raises(SynthesisError, match="non-finite"):
            engine.synthesize("Owned private text", "voice", 1, output)
    assert len(requests) == 1
    assert not output.exists()


def test_redirect_does_not_forward_source_to_another_server(tmp_path: Path) -> None:
    with (
        local_server(wav_bytes()) as (destination, forwarded),
        local_server(b"", status=307, location=destination + "/escape") as (url, requests),
    ):
        engine = OpenAIAudioEngine(url, "model", "voice")
        output = tmp_path / "redirect.wav"
        with pytest.raises(SynthesisError, match="redirects are not followed"):
            engine.synthesize("private source", "voice", 1, output)
    assert len(requests) == 1
    assert forwarded == []
    assert not output.exists()


def test_localhost_is_pinned_and_ignores_ambient_http_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = socket.getaddrinfo
    hosts: list[str] = []

    def numeric_only(host: str, *args: Any, **kwargs: Any) -> Any:
        hosts.append(host)
        assert host == "127.0.0.1", "only the literal loopback destination may be resolved"
        return original(host, *args, **kwargs)

    with (
        local_server(wav_bytes()) as (proxy, proxied),
        local_server(wav_bytes()) as (url, requests),
    ):
        monkeypatch.setenv("HTTP_PROXY", proxy)
        monkeypatch.setenv("http_proxy", proxy)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setattr(socket, "getaddrinfo", numeric_only)
        engine = OpenAIAudioEngine(url.replace("127.0.0.1", "localhost"), "model", "voice")
        assert engine.synthesize("private source", "voice", 1, tmp_path / "local.wav") == 100
    assert hosts == ["127.0.0.1"]
    assert len(requests) == 1
    assert proxied == []


def test_owned_http_server_does_not_consult_ambient_reverse_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []

    def controlled_lookup(host: str) -> str:
        lookups.append(host)
        return "owned.invalid"

    monkeypatch.setattr(socket, "getfqdn", controlled_lookup)
    with local_server(wav_bytes()):
        pass
    assert lookups == []
