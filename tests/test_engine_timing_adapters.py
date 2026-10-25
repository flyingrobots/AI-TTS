# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Kokoro backends report token times on the clip clock without changing audio."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soundfile as sf

from aitts.engines.kokoro import KokoroAssets, KokoroEngine
from aitts.engines.kokoro_mlx import KokoroMlxEngine
from aitts.timing import WordMark

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "Kokoro duration semantics (kokoro 0.9.4 join_timestamps): token times are seconds "
        "from each result's audio; results concatenate, so later results are offset"
    ),
]


def _kokoro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, results: list[Any]) -> KokoroEngine:
    class Model:
        def __init__(self, **_: object) -> None:
            pass

        def eval(self) -> Model:
            return self

    class Pipeline:
        def __init__(self, **_: object) -> None:
            self.g2p = lambda text: text

        def __call__(self, text: str, **_: object) -> Iterator[Any]:
            del text
            yield from results

    upstream = types.ModuleType("kokoro")
    upstream.KModel = Model  # type: ignore[attr-defined]
    upstream.KPipeline = Pipeline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro", upstream)
    return KokoroEngine(assets=KokoroAssets(download=lambda **_: str(tmp_path / "owned-model")))


def _token(text: str, start: float | None, end: float | None) -> types.SimpleNamespace:
    return types.SimpleNamespace(text=text, start_ts=start, end_ts=end)


def test_kokoro_offsets_each_result_by_the_audio_before_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = [
        types.SimpleNamespace(
            audio=np.full(12_000, 0.1, dtype=np.float32),  # 500 ms
            tokens=[_token("First", 0.1, 0.3), _token(".", 0.3, 0.4)],
        ),
        types.SimpleNamespace(
            audio=np.full(6_000, 0.1, dtype=np.float32),  # 250 ms
            tokens=[_token("Second", 0.05, 0.2), _token("unaligned", None, None)],
        ),
    ]
    engine = _kokoro(tmp_path, monkeypatch, results)

    duration, marks = engine.synthesize_timed("First. Second", "af_heart", 1.0, tmp_path / "a.wav")
    streamed = list(engine.stream_synthesize_timed("First. Second", "af_heart", 1.0))

    expected = (
        WordMark("First", 100.0, 300.0),
        WordMark(".", 300.0, 400.0),
        WordMark("Second", 550.0, 700.0),
    )
    assert duration == 750
    assert marks == expected
    assert len(sf.read(str(tmp_path / "a.wav"))[0]) == 18_000
    stream_marks = tuple(m for item in streamed if isinstance(item, tuple) for m in item)
    assert stream_marks == expected
    # Each result's marks precede its PCM, so live readers know the word first.
    first_pcm = next(i for i, item in enumerate(streamed) if isinstance(item, bytes))
    assert isinstance(streamed[0], tuple)
    assert first_pcm == 1
    pcm = b"".join(item for item in streamed if isinstance(item, bytes))
    assert len(pcm) == 18_000 * 2
    assert list(engine.stream_synthesize("First. Second", "af_heart", 1.0)) == [
        item for item in streamed if isinstance(item, bytes)
    ]


class _Array:
    """Stand-in for an MLX array: what the observer reads is ``tolist``."""

    def __init__(self, values: list[list[list[float]]]) -> None:
        self.values = values

    def tolist(self) -> list[list[list[float]]]:
        return self.values


def _logit(frames: float) -> list[float]:
    """A 50-bin projection whose sigmoid sum is exactly ``frames``."""
    probability = frames / 50
    return [float(np.log(probability / (1 - probability)))] * 50


class _Upstream:
    """kokoro-mlx 0.1.2 shape: forward computes durations it does not return."""

    def __init__(self, frames: list[float], *, samples: int | None = None) -> None:
        self._frames = frames
        self._samples = samples
        tokens = [
            types.SimpleNamespace(text="Hi", phonemes="hI", whitespace=" "),
            types.SimpleNamespace(text="there", phonemes="DEr", whitespace=""),
        ]
        outer = self

        class Phonemizer:
            def _g2p(self, text: str) -> tuple[str, list[types.SimpleNamespace]]:
                del text
                return "hI DEr", tokens

        class Predictor:
            def duration_proj(self, features: object) -> _Array:
                del features
                return _Array([[_logit(f) for f in outer._frames]])

        class Model:
            def __init__(self) -> None:
                self.predictor = Predictor()

            def forward(self, phonemes: str, ref_s: object, speed: float = 1.0) -> np.ndarray:
                del phonemes, ref_s, speed
                self.predictor.duration_proj(None)
                total = outer._samples or int(sum(round(f) for f in outer._frames)) * 600
                return np.full(total, 0.1, dtype=np.float32)

        self._model = Model()
        self._phonemizer = Phonemizer()

    def _get_phonemizer(self, language: object, voice: str) -> Any:
        del language, voice
        return self._phonemizer

    def generate_stream(self, text: str, **kwargs: object) -> Iterator[np.ndarray]:
        del text
        phonemes, _tokens = self._phonemizer._g2p("Hi there")
        speed = kwargs.get("speed", 1.0)
        assert isinstance(speed, float)
        yield self._model.forward(phonemes, None, speed)


def _mlx(upstream: _Upstream) -> KokoroMlxEngine:
    engine = KokoroMlxEngine(load_tts=lambda _directory: upstream)
    engine._model = upstream
    return engine


def test_mlx_reports_durations_its_forward_pass_predicted() -> None:
    # BOS, h I, space, D E r, EOS: hand-checked against join_timestamps.
    upstream = _Upstream([5, 2, 3, 4, 1, 1, 2, 6])
    engine = _mlx(upstream)

    items = list(engine.stream_synthesize_timed("Hi there", "bm_daniel", 1.0))

    assert items[0] == (WordMark("Hi", 50.0, 225.0), WordMark("there", 225.0, 375.0))
    assert sum(len(item) for item in items[1:]) == 24 * 600 * 2
    # The observation is removed afterwards: upstream objects are as they were.
    assert "forward" not in vars(upstream._model)
    assert "duration_proj" not in vars(upstream._model.predictor)
    assert "_g2p" not in vars(upstream._phonemizer)


def test_mlx_observation_that_does_not_match_the_audio_reports_nothing() -> None:
    upstream = _Upstream([5, 2, 3, 4, 1, 1, 2, 6], samples=1234)
    engine = _mlx(upstream)

    items = list(engine.stream_synthesize_timed("Hi there", "bm_daniel", 1.0))

    assert all(isinstance(item, bytes) for item in items)
    assert sum(len(item) for item in items) == 1234 * 2
