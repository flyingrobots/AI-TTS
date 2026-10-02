# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Kokoro's streaming boundary reports its own refusals exactly once."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from aitts.engine import SynthesisError
from aitts.engines.kokoro import KokoroAssets, KokoroEngine

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "engine boundary contract: a SynthesisError the adapter raises is the error the "
        "caller sees; only foreign upstream exceptions are wrapped"
    ),
]


def test_invalid_stream_samples_raise_the_adapter_error_unwrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Retire only if the streaming adapter stops validating upstream samples.
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
            yield types.SimpleNamespace(audio=np.array([0.0, np.nan]))

    upstream = types.ModuleType("kokoro")
    upstream.KModel = Model  # type: ignore[attr-defined]
    upstream.KPipeline = Pipeline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro", upstream)
    engine = KokoroEngine(assets=KokoroAssets(download=lambda **_: str(tmp_path / "owned-model")))

    with pytest.raises(SynthesisError) as raised:
        list(engine.stream_synthesize("Owned source", "af_heart", 1.0))

    assert str(raised.value) == "streaming engine produced invalid mono samples"
    assert not isinstance(raised.value.__cause__, SynthesisError), (
        "the adapter's own SynthesisError was wrapped in a second one"
    )
