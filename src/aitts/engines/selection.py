# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Startup engine selection: every local model runs only in a worker process."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from aitts.engines.managed import managed_engine
from aitts.engines.openai_compatible import OpenAIAudioEngine
from aitts.model_catalog import MODELS
from aitts.model_setup import installed_runtime
from aitts.store import Store

if TYPE_CHECKING:
    from pathlib import Path

    from aitts.engine import Engine

log = logging.getLogger(__name__)
DEFAULT_ENGINE = "kokoro"


def configured_engines(
    home: Path,
    *,
    override: str | None = None,
) -> tuple[Engine, dict[str, Engine]]:
    """Build the startup catalog without loading weights or contacting speech servers.

    The daemon process never imports a model package (issue #116). Each installed
    guided runtime becomes a worker-backed engine; the default model stays listed
    while uninstalled, and refuses requests with its setup command. Optional server
    configuration is deployment-scoped: changing it needs a daemon restart. The
    selected name is a live, persisted user preference.
    """
    store = Store(home / "state.db")
    try:
        name = override or store.get_setting("engine", DEFAULT_ENGINE)
    finally:
        store.close()
    engines: dict[str, Engine] = {
        model: managed_engine(model, root)
        for model in MODELS
        if (root := installed_runtime(home, model)) is not None
    }
    engines.setdefault(DEFAULT_ENGINE, managed_engine(DEFAULT_ENGINE, None))
    url = os.environ.get("AI_TTS_OPENAI_URL")
    if url:
        engines["openai-audio"] = OpenAIAudioEngine(
            url,
            os.environ.get("AI_TTS_OPENAI_MODEL", "kokoro"),
            os.environ.get("AI_TTS_OPENAI_VOICE", "af_heart"),
        )
    if name == "fake":
        from aitts.engine import FakeEngine  # noqa: PLC0415 - test and development engine

        engines[name] = FakeEngine(voices=["bm_daniel", "af_bella"])
    if name not in engines:
        if override is not None:
            msg = f"engine {name!r} is not configured in this daemon"
            raise ValueError(msg)
        # A live selection persists, but its runtime may be absent at launch.
        log.warning("event=configured_engine_unavailable fallback=kokoro")
        name = DEFAULT_ENGINE
    return engines[name], engines
