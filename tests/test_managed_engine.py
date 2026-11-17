# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import shutil
import sys
import wave
from pathlib import Path

import pytest

from aitts.engine import SynthesisError
from aitts.engines import managed
from aitts.engines.managed import ManagedEngine, ManagedStreamingEngine

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
        assert engine._process is None
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
