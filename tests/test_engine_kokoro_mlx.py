# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""MLX adapter contract at the local assets / generated WAV boundaries."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from aitts.engines.kokoro import VOICES, KokoroAssets
from aitts.engines.kokoro_mlx import KokoroMlxEngine
from tests.test_engine_offline import RecordingHub

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("Engine WAV contract and PROMPTS #2: local MLX inference at 24 kHz"),
]


class RecordingTts:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.loaded: list[Path] = []

    def load(self, directory: str) -> Any:
        self.loaded.append(Path(directory))
        return self

    def generate(self, text: str, **kwargs: object) -> SimpleNamespace:
        self.requests.append({"text": text, **kwargs})
        return SimpleNamespace(audio=np.full(2400, 0.125, dtype=np.float32), sample_rate=24000)

    def generate_stream(self, text: str, **kwargs: object) -> Iterator[np.ndarray]:
        yield self.generate(text, **kwargs).audio


def test_mlx_writes_audio_offline_and_forwards_requested_voice_speed(tmp_path: Path) -> None:
    filenames = {"config.json", "kokoro-v1_0.safetensors"} | {
        f"voices/{voice}.safetensors" for voice in VOICES
    }
    hub = RecordingHub(cached=filenames, root=tmp_path / "weights")
    backend = RecordingTts()
    engine = KokoroMlxEngine(assets=KokoroAssets(download=hub.download), load_tts=backend.load)
    engine.warmup()
    calls_after_warmup = list(hub.calls)
    output = tmp_path / "spoken.wav"
    duration = engine.synthesize("private test phrase", "bm_daniel", 1.25, output)
    assert output.is_file()
    audio, rate = sf.read(output)
    assert (rate, len(audio), duration) == (24000, 2400, 100)
    np.testing.assert_allclose(audio, np.full(2400, 0.125), atol=1e-5)
    assert backend.requests[-1] == {
        "text": "private test phrase",
        "voice": "bm_daniel",
        "speed": 1.25,
        "sample_rate": 24000,
    }
    assert backend.loaded == [tmp_path / "weights"]
    assert hub.calls == calls_after_warmup
    assert len(hub.calls) == len(filenames)
    assert hub.offline_only
    assert engine.list_voices() == list(VOICES)


def test_cold_synthesis_refuses_without_network_or_output(tmp_path: Path) -> None:
    from aitts.engine import SynthesisError  # noqa: PLC0415

    hub = RecordingHub(root=tmp_path)
    engine = KokoroMlxEngine(assets=KokoroAssets(download=hub.download))
    with pytest.raises(SynthesisError, match="warmup"):
        engine.synthesize("private source", "bm_daniel", 1.0, tmp_path / "out.wav")
    assert hub.calls == []
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize(("available", "expected"), [(True, "kokoro-mlx"), (False, "kokoro")])
def test_engine_selection_reports_actual_backend_with_fallback(
    *, available: bool, expected: str
) -> None:
    from aitts.engines.selection import select_engine  # noqa: PLC0415

    selected = select_engine("kokoro-mlx", probe_mlx=lambda: available)
    assert selected.name == expected
    assert selected.is_local is True


def test_model_warmup_primes_inference_only_once(tmp_path: Path) -> None:
    hub = RecordingHub(root=tmp_path)
    backend = RecordingTts()
    engine = KokoroMlxEngine(assets=KokoroAssets(download=hub.download), load_tts=backend.load)
    engine.warmup()
    engine.warmup()
    assert len(backend.loaded) == 1
    assert backend.requests == [
        {"text": "Ready.", "voice": "bm_daniel", "speed": 1.0, "sample_rate": 24000},
    ]


@pytest.mark.parametrize("fault", ["empty", "nan", "rate", "stereo"])
def test_invalid_upstream_audio_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from aitts.engine import SynthesisError  # noqa: PLC0415

    hub = RecordingHub(root=tmp_path / "weights")
    backend = RecordingTts()
    engine = KokoroMlxEngine(assets=KokoroAssets(download=hub.download), load_tts=backend.load)
    engine.warmup()
    malformed = {
        "empty": np.array([], dtype=np.float32),
        "nan": np.array([np.nan], dtype=np.float32),
        "rate": np.zeros(2400, dtype=np.float32),
        "stereo": np.zeros((2400, 2), dtype=np.float32),
    }

    def generate(*args: object, **kwargs: object) -> SimpleNamespace:
        del args, kwargs
        return SimpleNamespace(
            audio=malformed[fault], sample_rate=48000 if fault == "rate" else 24000
        )

    monkeypatch.setattr(backend, "generate", generate)
    output = tmp_path / "spoken.wav"
    with pytest.raises(SynthesisError, match="audio"):
        engine.synthesize("private phrase", "bm_daniel", 1.0, output)
    assert not output.exists()


def test_startup_reads_persisted_engine_and_honors_cli_override(tmp_path: Path) -> None:
    from aitts.engines.selection import configured_engine  # noqa: PLC0415
    from aitts.store import Store  # noqa: PLC0415

    store = Store(tmp_path / "state.db")
    store.set_setting("engine", "kokoro-mlx")
    store.close()
    assert configured_engine(tmp_path, probe_mlx=lambda: True).name == "kokoro-mlx"
    assert configured_engine(tmp_path, override="kokoro", probe_mlx=lambda: True).name == "kokoro"


def test_mlx_stream_yields_bounded_pcm_matching_generated_samples(tmp_path: Path) -> None:
    class LongerTts(RecordingTts):
        def generate(self, text: str, **kwargs: object) -> SimpleNamespace:
            del text, kwargs
            return SimpleNamespace(
                audio=np.linspace(-1.25, 1.25, 5001, dtype=np.float32), sample_rate=24000
            )

    hub = RecordingHub(root=tmp_path)
    backend = LongerTts()
    engine = KokoroMlxEngine(assets=KokoroAssets(download=hub.download), load_tts=backend.load)
    engine.warmup()
    asset_calls = list(hub.calls)
    chunks = list(engine.stream_synthesize("Controlled source", "bm_daniel", 1.0))
    assert [len(chunk) for chunk in chunks] == [4800, 4800, 402]
    expected = np.clip(np.linspace(-1.25, 1.25, 5001, dtype=np.float32), -1, 1 - 1 / 32768)
    assert b"".join(chunks) == (expected * 32768).astype("<i2").tobytes()
    assert hub.calls == asset_calls


def test_mlx_stream_does_not_wait_for_later_model_chunks(tmp_path: Path) -> None:
    class ChunkedTts(RecordingTts):
        tail_requested = False

        def generate_stream(self, text: str, **kwargs: object) -> Iterator[np.ndarray]:
            del text, kwargs
            yield np.full(2400, 0.25, dtype=np.float32)
            self.tail_requested = True
            yield np.full(2400, 0.5, dtype=np.float32)

    hub = RecordingHub(root=tmp_path)
    backend = ChunkedTts()
    engine = KokoroMlxEngine(assets=KokoroAssets(download=hub.download), load_tts=backend.load)
    engine.warmup()
    chunks = engine.stream_synthesize("Two controlled chunks", "bm_daniel", 1.0)
    try:
        assert next(chunks) == b"\x00\x20" * 2400
        assert backend.tail_requested is False
        assert list(chunks) == [b"\x00\x40" * 2400]
    finally:
        chunks.close()
