# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Optional backend selection at the installed-runtime boundary."""

import importlib.util
import platform
import sys
from types import ModuleType, SimpleNamespace

import pytest

from aitts.engines import selection

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("MLX selection requires packages, English assets and available Metal"),
]


@pytest.mark.parametrize("missing", [None, "kokoro_mlx", "en_core_web_sm"])
def test_missing_runtime_assets_select_reference_backend(
    monkeypatch: pytest.MonkeyPatch, missing: str | None
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: None if name == missing else object()
    )
    mlx = ModuleType("mlx")
    core = ModuleType("mlx.core")
    core.metal = SimpleNamespace(is_available=lambda: True)  # type: ignore[attr-defined]
    mlx.core = core  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", core)

    actual = selection.select_engine("kokoro-mlx")

    assert actual.name == ("kokoro-mlx" if missing is None else "kokoro")
