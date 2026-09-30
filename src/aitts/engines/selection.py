# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Startup engine selection with an explicit optional-MLX fallback."""

from __future__ import annotations

import importlib.util
import logging
import platform
import sys
from typing import TYPE_CHECKING

from aitts.engines.kokoro import KokoroEngine
from aitts.engines.kokoro_mlx import KokoroMlxEngine
from aitts.store import Store

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from aitts.engine import Engine

log = logging.getLogger(__name__)
ENGINE_NAMES = ("kokoro", "kokoro-mlx", "fake")


def mlx_available() -> bool:
    """Probe supported runtime, installed package and the Metal backend."""
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info >= (3, 13):
        return False
    if importlib.util.find_spec("kokoro_mlx") is None:
        return False
    try:
        import mlx.core as mx  # noqa: PLC0415 - optional hardware backend

        return bool(mx.metal.is_available())
    except (ImportError, OSError, RuntimeError):
        return False


def select_engine(name: str, *, probe_mlx: Callable[[], bool] = mlx_available) -> Engine:
    """Select a configured adapter; unavailable MLX falls back to reference Kokoro."""
    if name == "fake":
        from aitts.engine import FakeEngine  # noqa: PLC0415

        return FakeEngine(voices=["bm_daniel", "af_bella"])
    if name == "kokoro-mlx":
        if probe_mlx():
            return KokoroMlxEngine()
        log.warning("event=mlx_backend_unavailable fallback=kokoro")
        return KokoroEngine()
    if name == "kokoro":
        return KokoroEngine()
    msg = f"unknown engine {name!r}"
    raise ValueError(msg)


def configured_engine(
    home: Path,
    *,
    override: str | None = None,
    probe_mlx: Callable[[], bool] = mlx_available,
) -> Engine:
    """Load the persisted backend preference, with an explicit CLI override."""
    store = Store(home / "state.db")
    try:
        name = override or store.get_setting("engine", "kokoro")
    finally:
        store.close()
    return select_engine(name, probe_mlx=probe_mlx)
