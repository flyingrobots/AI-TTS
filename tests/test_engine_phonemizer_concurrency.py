# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
"""Concurrent callers must not mix phonemizer state; neural rendering stays parallel."""

from __future__ import annotations

import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from aitts.engines import kokoro

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "Kokoro engine contract: each concurrent synthesis retains its own phonemes and audio"
    ),
]


def test_concurrent_synthesis_isolates_phonemes_without_serializing_inference(  # noqa: C901 - one controlled two-caller schedule with upstream doubles
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_inside = threading.Event()
    competitor_arrived = threading.Event()
    inference = threading.Barrier(2, timeout=3)

    class ScheduledGate:
        """Witness a blocked competing call instead of relying on a settle-time sleep."""

        def __init__(self) -> None:
            self.lock = threading.Lock()

        def __enter__(self) -> None:
            if not self.lock.acquire(blocking=False):
                competitor_arrived.set()
                if not self.lock.acquire(timeout=3):
                    raise TimeoutError

        def __exit__(self, *_: object) -> None:
            self.lock.release()

    class SharedPhonemizer:
        count = 0

        def __call__(self, text: str) -> int:
            self.count = 1 if text == "one" else 4
            if text == "one":
                first_inside.set()
                if not competitor_arrived.wait(3):
                    raise TimeoutError
            else:
                competitor_arrived.set()
            return self.count

    class Pipeline:
        def __init__(self, **_: object) -> None:
            self.g2p = SharedPhonemizer()

        def __call__(self, text: str, **_: object) -> Any:
            phonemes = self.g2p(text)
            # Both renders must reach inference together; a whole-pipeline lock
            # would deadlock this owned, bounded schedule.
            inference.wait()
            yield types.SimpleNamespace(audio=np.full(24, phonemes / 10, dtype=np.float32))

    class Model:
        def __init__(self, **_: object) -> None:
            pass

        def eval(self) -> Model:
            return self

    upstream = types.ModuleType("kokoro")
    upstream.KPipeline = Pipeline  # type: ignore[attr-defined]
    upstream.KModel = Model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro", upstream)
    monkeypatch.setattr(kokoro, "_PHONEMIZER_GATE", ScheduledGate(), raising=False)

    def asset(**_: object) -> str:
        return str(tmp_path / "asset")

    engine = kokoro.KokoroEngine(assets=kokoro.KokoroAssets(download=asset))
    paths = [tmp_path / "one.wav", tmp_path / "four.wav"]
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(engine.synthesize, "one", "af_heart", 1.0, paths[0])
        assert first_inside.wait(3), "first call did not reach phonemization"
        second = workers.submit(engine.synthesize, "four", "af_heart", 1.0, paths[1])
        durations = [first.result(timeout=5), second.result(timeout=5)]
    assert durations == [1, 1]
    assert [float(sf.read(path)[0][0]) for path in paths] == pytest.approx(
        [0.1, 0.4], abs=1 / 32768
    )
