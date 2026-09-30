# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Manual inference gauge rejects malformed artifacts through its adapter boundary."""

import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from scripts.benchmarks.mlx import measure_inference

from aitts.engines.kokoro_mlx import KokoroMlxEngine

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("Benchmark WAV/PCM format and trial inventory"),
]


class OwnedEngine:
    def __init__(self, *, bad_wav: bool = False, bad_pcm: bool = False) -> None:
        self.bad_wav, self.bad_pcm = bad_wav, bad_pcm

    def synthesize(self, _text: str, _voice: str, _speed: float, path: Path) -> int:
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, 22050 if self.bad_wav else 24000, 2400, "NONE", ""))
            output.writeframes(b"\x01\x00" * 2400)
        return 100

    def stream_synthesize(self, _text: str, _voice: str, _speed: float) -> Iterator[bytes]:
        yield b"" if self.bad_pcm else b"\x01\x00" * 2400


def test_inference_gauge_records_file_and_stream_trials() -> None:
    report: dict[str, Any] = {"trials": []}
    stream = measure_inference(cast("KokoroMlxEngine", OwnedEngine()), 2, report, lambda _: None)
    assert len(report["trials"]) == len(stream) == 2
    assert [trial["audio_ms"] for trial in report["trials"]] == [100, 100]
    assert [trial["pcm_bytes"] for trial in stream] == [4800, 4800]


@pytest.mark.parametrize("fault", ["wav", "pcm"])
def test_inference_gauge_rejects_malformed_audio(fault: str) -> None:
    engine = OwnedEngine(bad_wav=fault == "wav", bad_pcm=fault == "pcm")
    with pytest.raises(RuntimeError, match=r"invalid WAV|invalid streaming PCM"):
        measure_inference(cast("KokoroMlxEngine", engine), 1, {"trials": []}, lambda _: None)
