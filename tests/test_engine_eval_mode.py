# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The model must be in evaluation mode before it speaks a word.

A PyTorch module defaults to *training* mode, in which dropout layers randomly
zero activations and normalisation layers track running statistics. Upstream's
pipeline calls ``.eval()`` when it constructs its own model — but this adapter
deliberately constructs the model itself and passes it in, so that voice packs
resolve from the local cache instead of through the model host on every load.
Bypassing that construction also bypassed the ``.eval()``.

The result was nine active dropout layers in the pitch and duration predictor,
randomly perturbing prosody on every clip. Nothing failed, nothing logged, and
no test noticed: the engine tests stub the pipeline, so the real module tree is
never inspected.

``@torch.no_grad()`` upstream does not help here. Gradients and module mode are
different things — one stops the autograd graph, the other stops dropout.
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("PyTorch's requirement that inference runs in eval mode"),
]


class RecordingModel:
    """Stands in for KModel, recording the mode it was put into."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.training = True
        self.eval_calls = 0

    def eval(self) -> RecordingModel:
        self.eval_calls += 1
        self.training = False
        return self


@pytest.fixture
def fake_kokoro(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Install a stand-in ``kokoro`` module so no real weights are loaded."""
    module = types.ModuleType("kokoro")
    module.KModel = RecordingModel  # type: ignore[attr-defined]
    module.KPipeline = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro", module)
    return module


@pytest.mark.usefixtures("fake_kokoro")
def test_the_shared_model_is_put_into_eval_mode(tmp_path: Path) -> None:
    from aitts.engines.kokoro import KokoroAssets, KokoroEngine  # noqa: PLC0415

    def resolve(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"weights")
        return str(path)

    engine = KokoroEngine(assets=KokoroAssets(download=resolve))
    model = engine._shared_model()

    # Dropout during inference randomly perturbs pitch and duration. The audio
    # still sounds like speech, which is exactly why this went unnoticed.
    assert model.training is False
    assert model.eval_calls == 1


@pytest.mark.usefixtures("fake_kokoro")
def test_the_model_is_built_once_and_stays_in_eval_mode(tmp_path: Path) -> None:
    from aitts.engines.kokoro import KokoroAssets, KokoroEngine  # noqa: PLC0415

    def resolve(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"weights")
        return str(path)

    engine = KokoroEngine(assets=KokoroAssets(download=resolve))
    first = engine._shared_model()
    second = engine._shared_model()

    # One model shared by every language pipeline, and eval() applied to it
    # once rather than on each retrieval.
    assert first is second
    assert first.eval_calls == 1
