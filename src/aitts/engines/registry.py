# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Resident engines with independent preparation, failure and reload lifecycles."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from aitts.engine import SynthesisError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aitts.engine import Engine


class EngineRegistry:
    """Keep prepared adapters resident while the next-clip default changes."""

    def __init__(self, engines: Mapping[str, Engine]) -> None:
        """Register concrete adapters without preparing or downloading models."""
        self.engines = dict(engines)
        self._locks = {name: threading.Lock() for name in engines}
        self._states = dict.fromkeys(engines, "cold")

    def state(self, name: str) -> str:
        """Read preparation status without waiting on a long model load."""
        return self._states[name]

    def prepare(self, name: str) -> None:
        """Prepare a backend once; concurrent callers share the same outcome."""
        with self._locks[name]:
            if self._states[name] == "ready":
                return
            if self._states[name] == "failed":
                msg = f"engine {name!r} failed to prepare; restart the model to retry"
                raise SynthesisError(msg)
            self._states[name] = "loading"
            try:
                self.engines[name].warmup()
            except Exception:
                self._states[name] = "failed"
                raise
            self._states[name] = "ready"

    def restart(self, name: str) -> None:
        """Reload one backend while preserving every other resident model."""
        with self._locks[name]:
            self._states[name] = "reloading"
            try:
                engine = self.engines[name]
                restart = getattr(engine, "restart", engine.warmup)
                restart()
            except Exception:
                self._states[name] = "failed"
                raise
            self._states[name] = "ready"
