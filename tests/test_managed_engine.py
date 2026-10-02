# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

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
