# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import shutil
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aitts import model_worker
from aitts.engine import SynthesisError
from aitts.engines import managed
from aitts.engines.managed import ManagedEngine, ManagedStreamingEngine

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "worker preserves native WAV and PCM; interrupted streams cannot contaminate later clips"
    ),
]


@pytest.fixture
def worker_root(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "venv").symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
    package = root / "adapter/aitts"
    shutil.copytree(
        Path(managed.__file__).parents[1], package, ignore=shutil.ignore_patterns("__pycache__")
    )
    (package / "model_worker.py").rename(package / "worker_contract.py")
    (package / "model_worker.py").write_text("""
from aitts import worker_contract
from aitts.engine import FakeEngine
class OwnedModel(FakeEngine):
    def stream_synthesize(self, text, voice, speed):
        if text == "bad":
            yield b"odd"
        else:
            yield text.encode() * 2
            yield b"\\x03\\x00" * 100
    def evidence(self, voice):
        weights = {"sha256": "owned hash", "bytes": 42}
        return {"repository": "owned", "voice": voice, "files": {"weights": weights}}
    def warmup(self):
        print("upstream noise must not corrupt framing")
        super().warmup()
worker_contract.local_engine = lambda name, root: OwnedModel(["voice"], duration_ms=100)
worker_contract.main()
""")
    return root


def test_file_worker_preserves_real_wav_and_restarts_offline(
    worker_root: Path, tmp_path: Path
) -> None:
    engine = ManagedEngine("chatterbox", worker_root)
    try:
        engine.warmup()
        out = tmp_path / "clip.wav"
        assert engine.synthesize("clip", "default", 1.0, out) == 100
        with wave.open(str(out)) as audio:
            assert audio.getframerate() == 24000
            assert audio.getnchannels() == 1
            assert audio.readframes(audio.getnframes()) == b"\x00\x00" * 24
        metadata = engine.evidence("default")
        assert metadata["repository"] == "owned"
        assert metadata["voice"] == "default"
        assert metadata["files"] == {"weights": {"sha256": "owned hash", "bytes": 42}}
        assert metadata["runtime"]["python"] == sys.version.split()[0]
        engine.close()
        engine.restart()
        assert engine.synthesize("next", "default", 1.0, out) == 100
    finally:
        engine.close()


def test_stream_abort_discards_unread_audio_and_keeps_next_clip_usable(worker_root: Path) -> None:
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        first = engine.stream_synthesize("A", "voice", 1.0)
        assert next(first) == b"AA"
        first.close()  # type: ignore[attr-defined]
        assert list(engine.stream_synthesize("B", "voice", 1.0)) == [b"BB", b"\x03\x00" * 100]
        assert list(engine.stream_synthesize("C", "voice", 1.0)) == [b"CC", b"\x03\x00" * 100]
    finally:
        engine.close()


def test_invalid_pcm_is_rejected_and_next_clip_can_recover(worker_root: Path) -> None:
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        with pytest.raises(SynthesisError, match="invalid PCM"):
            list(engine.stream_synthesize("bad", "voice", 1.0))
        assert list(engine.stream_synthesize("D", "voice", 1.0)) == [b"DD", b"\x03\x00" * 100]
    finally:
        engine.close()


def test_truncated_worker_response_fails_within_owned_deadline(
    worker_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (worker_root / "adapter/aitts/model_worker.py").write_text(
        'import sys, time; sys.stdout.write("{"); sys.stdout.flush(); time.sleep(10)'
    )
    monkeypatch.setattr(managed, "_RESPONSE_TIMEOUT", 0.1)
    engine = ManagedEngine("chatterbox", worker_root)
    try:
        with pytest.raises(SynthesisError, match="timed out"):
            engine.warmup()
    finally:
        engine.close()


# Issue #116: every local model runs only behind this boundary, so its known
# failure modes and its golden workload are pinned here for each catalog engine.


def _worker(root: Path, body: str) -> None:
    (root / "adapter/aitts/model_worker.py").write_text(
        "from aitts import worker_contract\nfrom aitts.engine import FakeEngine\n" + body
    )


@pytest.mark.parametrize("name", ["kokoro", "kokoro-mlx", "chatterbox"])
def test_each_catalog_engine_synthesizes_and_streams_through_a_worker(
    worker_root: Path, tmp_path: Path, name: str
) -> None:
    """Oracle: issue #116 golden; every local engine delivers audio only through the worker."""
    engine = managed.managed_engine(name, worker_root)
    try:
        engine.warmup()
        out = tmp_path / f"{name}.wav"
        assert engine.synthesize("clip", "voice", 1.0, out) == 100
        with wave.open(str(out)) as audio:
            assert audio.readframes(audio.getnframes()) == b"\x00\x00" * 24
        if name != "chatterbox":
            stream = engine.stream_synthesize("A", "voice", 1.0)  # type: ignore[attr-defined]
            assert list(stream) == [b"AA", b"\x03\x00" * 100]
        assert engine._process is not None
        assert engine._process.pid != os.getpid()
    finally:
        engine.close()


def test_native_writes_to_the_output_descriptor_cannot_corrupt_frames(worker_root: Path) -> None:
    """Oracle: known failure mode; a model library writing to fd 1 must not reach the pipe."""
    _worker(
        worker_root,
        """import os
class Noisy(FakeEngine):
    def stream_synthesize(self, text, voice, speed):
        os.write(1, b"native library noise\\n")
        yield text.encode() * 2
worker_contract.local_engine = lambda name, root: Noisy(["voice"], duration_ms=100)
worker_contract.main()
""",
    )
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        assert list(engine.stream_synthesize("N", "voice", 1.0)) == [b"NN"]
        assert list(engine.stream_synthesize("M", "voice", 1.0)) == [b"MM"]
    finally:
        engine.close()


def test_worker_exit_during_synthesis_fails_the_clip_and_restart_recovers(
    worker_root: Path,
) -> None:
    """Oracle: edge case; a worker that dies mid-stream yields a typed failure, never stale PCM."""
    _worker(
        worker_root,
        """import os
class Dying(FakeEngine):
    def stream_synthesize(self, text, voice, speed):
        yield text.encode() * 2
        if text == "die":
            os._exit(3)
        yield b"\\x03\\x00"
worker_contract.local_engine = lambda name, root: Dying(["voice"], duration_ms=100)
worker_contract.main()
""",
    )
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        received: list[bytes] = []
        with pytest.raises(SynthesisError, match="invalid response"):
            received.extend(engine.stream_synthesize("die", "voice", 1.0))
        assert received == [b"diedie"]
        engine.restart()
        assert list(engine.stream_synthesize("ok", "voice", 1.0)) == [b"okok", b"\x03\x00"]
    finally:
        engine.close()


def test_silent_worker_fails_within_the_owned_deadline(
    worker_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oracle: edge case; a worker that gives no reply in the time limit is stopped."""
    _worker(worker_root, "import time\ntime.sleep(30)\n")
    monkeypatch.setattr(managed, "_RESPONSE_TIMEOUT", 0.2)
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        with pytest.raises(SynthesisError, match="timed out"):
            list(engine.stream_synthesize("late", "voice", 1.0))
    finally:
        engine.close()


def test_one_worker_answers_a_thousand_short_requests_in_order(worker_root: Path) -> None:
    """Oracle: stress; each reply equals the deterministic echo of its own request."""
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        for index in range(1000):
            text = f"r{index:04d}"
            assert list(engine.stream_synthesize(text, "voice", 1.0)) == [
                text.encode() * 2,
                b"\x03\x00" * 100,
            ], index
    finally:
        engine.close()


# Issue #126: audio leaves the control pipe and moves as length-prefixed binary
# frames on a second pipe; the first control message names the protocol version.


def _chunked_reader(data: bytes, sizes: list[int]) -> Callable[[int], bytes]:
    """Return a pipe double that answers each read with at most the next drawn size."""
    view = memoryview(data)
    position = 0
    turn = 0

    def read(limit: int) -> bytes:
        nonlocal position, turn
        size = min(limit, sizes[turn % len(sizes)])
        turn += 1
        block = bytes(view[position : position + size])
        position += len(block)
        return block

    return read


@settings(max_examples=200, deadline=None)
@given(
    blocks=st.lists(st.binary(min_size=1, max_size=4096), max_size=8),
    sizes=st.lists(st.integers(min_value=1, max_value=5000), min_size=1, max_size=16),
)
def test_random_frames_and_random_read_sizes_give_the_same_bytes(
    blocks: list[bytes], sizes: list[int]
) -> None:
    """Oracle: issue #126 fuzz; any read pattern recovers each frame byte for byte."""
    wire = b"".join(model_worker.encode_frame(block) for block in blocks)
    wire += model_worker.encode_frame(b"")
    read = _chunked_reader(wire, sizes)
    received = []
    while frame := managed.read_frame(read):
        received.append(frame)
    assert received == blocks


def test_zero_length_frame_and_frame_at_the_limit_are_read_exactly() -> None:
    """Oracle: issue #126 edges; the empty frame is the end mark and the limit is inclusive."""
    largest = bytes(range(256)) * (model_worker.FRAME_LIMIT // 256)
    wire = model_worker.encode_frame(largest) + model_worker.encode_frame(b"")
    read = _chunked_reader(wire, [65536])
    assert managed.read_frame(read) == largest
    assert managed.read_frame(read) == b""


@pytest.mark.parametrize("cut", [0, 2, 4, 5, 4 + 99])
def test_pipe_closed_inside_a_frame_is_never_read_as_a_full_frame(cut: int) -> None:
    """Oracle: issue #126 known failure mode; a partial frame is a typed failure."""
    wire = model_worker.encode_frame(b"\x01" * 100)[:cut]
    with pytest.raises(SynthesisError, match="invalid response"):
        managed.read_frame(_chunked_reader(wire, [7]))


def test_frame_above_the_limit_is_refused_before_it_is_read() -> None:
    """Oracle: issue #126 edge; a length above 512 KiB is refused even when the bytes follow."""
    size = model_worker.FRAME_LIMIT + 1
    wire = size.to_bytes(4, "big") + b"\x00" * size
    with pytest.raises(SynthesisError, match="invalid response"):
        managed.read_frame(_chunked_reader(wire, [65536]))


def test_worker_audio_arrives_byte_for_byte_as_binary_frames(worker_root: Path) -> None:
    """Oracle: issue #126 golden; a block larger than one JSON line could hold arrives intact."""
    block = bytes(range(256)) * (3 * model_worker.FRAME_LIMIT // 256)
    _worker(
        worker_root,
        f"""class Big(FakeEngine):
    def stream_synthesize(self, text, voice, speed):
        yield bytes(range(256)) * {len(block) // 256}
        yield b"\\x05\\x00"
worker_contract.local_engine = lambda name, root: Big(["voice"], duration_ms=100)
worker_contract.main()
""",
    )
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        assert b"".join(engine.stream_synthesize("big", "voice", 1.0)) == block + b"\x05\x00"
    finally:
        engine.close()


@pytest.mark.parametrize(
    "hello",
    ['{"protocol": 1}', '{"protocol": "2"}', '{"ok": true}'],
)
def test_daemon_refuses_a_worker_with_another_protocol_version(
    worker_root: Path, hello: str
) -> None:
    """Oracle: issue #126; a version other than the daemon's is a typed refusal at start."""
    (worker_root / "adapter/aitts/model_worker.py").write_text(
        f"import sys, time\nsys.stdout.write({hello!r} + '\\n')\n"
        "sys.stdout.flush()\ntime.sleep(10)\n"
    )
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        with pytest.raises(managed.WorkerProtocolError, match="protocol"):
            engine.warmup()
    finally:
        engine.close()


def test_daemon_refuses_a_worker_that_exits_before_the_handshake(worker_root: Path) -> None:
    """Oracle: issue #126; an older worker that cannot parse the new start fails typed."""
    (worker_root / "adapter/aitts/model_worker.py").write_text("raise SystemExit(2)\n")
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        with pytest.raises(managed.WorkerProtocolError, match="protocol"):
            engine.warmup()
    finally:
        engine.close()


def test_worker_announces_the_daemon_protocol_version_first(worker_root: Path) -> None:
    """Oracle: issue #126; the worker and the daemon agree on one version at start."""
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        engine.warmup()
        assert engine.protocol_version == model_worker.PROTOCOL_VERSION == 2
    finally:
        engine.close()


def test_model_failure_inside_a_stream_ends_the_frames_and_fails_typed(worker_root: Path) -> None:
    """Oracle: issue #126; a model error closes the audio frames, so the reply is never lost."""
    _worker(
        worker_root,
        """class Failing(FakeEngine):
    def stream_synthesize(self, text, voice, speed):
        yield text.encode() * 2
        if text == "fail":
            raise RuntimeError("model failed")
worker_contract.local_engine = lambda name, root: Failing(["voice"], duration_ms=100)
worker_contract.main()
""",
    )
    engine = ManagedStreamingEngine("kokoro", worker_root)
    try:
        received: list[bytes] = []
        with pytest.raises(SynthesisError, match="could not render"):
            received.extend(engine.stream_synthesize("fail", "voice", 1.0))
        assert received == [b"failfail"]
        assert list(engine.stream_synthesize("ok", "voice", 1.0)) == [b"okok"]
    finally:
        engine.close()
