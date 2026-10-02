# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Startup engine selection with an explicit optional-MLX fallback."""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aitts.engines.chatterbox import ChatterboxEngine
from aitts.engines.kokoro import KokoroEngine
from aitts.engines.kokoro_mlx import KokoroMlxEngine
from aitts.engines.openai_compatible import OpenAIAudioEngine
from aitts.store import Store

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.engine import Engine

log = logging.getLogger(__name__)
ENGINE_NAMES = ("kokoro", "kokoro-mlx", "fake")


def mlx_available() -> bool:
    """Probe the runtime, required packages/language assets, and Metal backend."""
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info >= (3, 13):
        return False
    if any(importlib.util.find_spec(name) is None for name in ("kokoro_mlx", "en_core_web_sm")):
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


def configured_engines(
    home: Path,
    *,
    override: str | None = None,
    probe_mlx: Callable[[], bool] = mlx_available,
) -> tuple[Engine, dict[str, Engine]]:
    """Build the startup catalog without loading weights or contacting speech servers.

    Optional server/model configuration is deployment-scoped: changing it needs
    a daemon restart. The selected name is a live, persisted user preference.
    """
    store = Store(home / "state.db")
    try:
        name = override or store.get_setting("engine", "kokoro")
    finally:
        store.close()
    engines: dict[str, Engine] = {"kokoro": KokoroEngine()}
    if probe_mlx():
        engines["kokoro-mlx"] = KokoroMlxEngine()
    elif name == "kokoro-mlx":
        log.warning("event=mlx_backend_unavailable fallback=kokoro")
        name = "kokoro"
    url = os.environ.get("AI_TTS_OPENAI_URL")
    if url:
        engines["openai-audio"] = OpenAIAudioEngine(
            url,
            os.environ.get("AI_TTS_OPENAI_MODEL", "kokoro"),
            os.environ.get("AI_TTS_OPENAI_VOICE", "af_heart"),
        )
    directory = os.environ.get("AI_TTS_CHATTERBOX_MODEL_DIR")
    if directory:
        engines["chatterbox"] = ChatterboxEngine(
            Path(directory),
            device=os.environ.get("AI_TTS_CHATTERBOX_DEVICE", "cpu"),
        )
    if name == "fake":
        engines[name] = select_engine(name)
    if name not in engines:
        if override is not None:
            msg = f"engine {name!r} is not configured in this daemon"
            raise ValueError(msg)
        # A live selection persists, but its adapter's environment may be absent at launch.
        log.warning("event=configured_engine_unavailable fallback=kokoro")
        name = "kokoro"
    return engines[name], engines
