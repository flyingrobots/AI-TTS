# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Chatterbox Turbo's local loader and tensor-to-WAV contract."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from aitts.engine import SynthesisError
from aitts.engines.chatterbox import ChatterboxEngine

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "ChatterboxTurboTTS.from_local/generate: local snapshot, native 24 kHz mono tensor"
    ),
]


class Tensor:
    def __init__(self, samples: np.ndarray) -> None:
        self.samples = samples

    def detach(self) -> "Tensor":
        return self

    def cpu(self) -> "Tensor":
        return self

    def numpy(self) -> np.ndarray:
        return self.samples


class LocalTurbo:
    sr = 24000

    def __init__(self) -> None:
        self.loaded: list[tuple[Path, str]] = []
        self.requests: list[str] = []
        self.audio = np.full((1, 2400), 0.1234567, dtype=np.float32)

    def load(self, directory: Path, device: str) -> Any:
        self.loaded.append((directory, device))
        return self

    def generate(self, text: str) -> Tensor:
        self.requests.append(text)
        return Tensor(self.audio)


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    # Independent upstream file manifest; deliberately not imported from implementation.
    for name in (
        "ve.safetensors",
        "t3_turbo_v1.safetensors",
        "s3gen_meanflow.safetensors",
        "conds.pt",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "added_tokens.json",
        "special_tokens_map.json",
    ):
        (tmp_path / name).write_bytes(b"owned model fixture")
    return tmp_path


def test_local_model_is_primed_once_and_native_samples_are_preserved(snapshot: Path) -> None:
    backend = LocalTurbo()
    engine = ChatterboxEngine(snapshot, load_model=backend.load)
    engine.warmup()
    engine.warmup()
    output = snapshot / "speech.wav"
    assert engine.synthesize("owned private source", "default", 1, output) == 100
    audio, rate = sf.read(output, dtype="float32")
    assert rate == 24000
    np.testing.assert_array_equal(audio, backend.audio[0])
    assert backend.loaded == [(snapshot.resolve(), "cpu")]
    assert backend.requests == ["Ready.", "owned private source"]
    assert engine.list_voices() == ["default"]
    engine.restart()
    assert backend.loaded == [(snapshot.resolve(), "cpu")] * 2
    assert backend.requests[-1] == "Ready."


def test_missing_local_assets_fail_before_loading_or_speaking(tmp_path: Path) -> None:
    backend = LocalTurbo()
    engine = ChatterboxEngine(tmp_path, load_model=backend.load)
    with pytest.raises(SynthesisError, match="incomplete local"):
        engine.warmup()
    with pytest.raises(SynthesisError, match="warmup must finish"):
        engine.synthesize("owned text", "default", 1, tmp_path / "speech.wav")
    assert backend.loaded == []
    assert backend.requests == []
    assert not (tmp_path / "speech.wav").exists()


@pytest.mark.parametrize(("voice", "speed"), [("unknown", 1), ("default", 1.5)])
def test_unsupported_voice_or_speed_is_not_silently_ignored(
    snapshot: Path, voice: str, speed: float
) -> None:
    backend = LocalTurbo()
    engine = ChatterboxEngine(snapshot, load_model=backend.load)
    engine.warmup()
    with pytest.raises(SynthesisError, match="generation speed 1"):
        engine.synthesize("owned text", voice, speed, snapshot / "speech.wav")
    assert backend.requests == ["Ready."]
    assert not (snapshot / "speech.wav").exists()


@pytest.mark.parametrize("fault", ["empty", "stereo", "nan", "rate"])
def test_malformed_model_output_is_not_published(snapshot: Path, fault: str) -> None:
    backend = LocalTurbo()
    engine = ChatterboxEngine(snapshot, load_model=backend.load)
    engine.warmup()
    if fault == "rate":
        backend.sr = 48000
    else:
        backend.audio = {
            "empty": np.empty((1, 0)),
            "stereo": np.zeros((2, 2400)),
            "nan": np.full((1, 2400), np.nan),
        }[fault]
    with pytest.raises(SynthesisError, match="synthesis failed"):
        engine.synthesize("owned text", "default", 1, snapshot / "speech.wav")
    assert not (snapshot / "speech.wav").exists()
