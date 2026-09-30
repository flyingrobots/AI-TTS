# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Queued source cannot reach a backend until preparation has finished."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink
from tests.test_ipc import rpc

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("MLX preparation must finish before queued confidential synthesis starts"),
]


class GatedWarmupEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__(voices=["bm_daniel"])
        self.started = threading.Event()
        self.release = threading.Event()
        self.synthesized = threading.Event()
        self.premature = False

    def warmup(self) -> None:
        self.started.set()
        if not self.release.wait(5):
            msg = "test did not release warmup"
            raise TimeoutError(msg)

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        self.premature = not self.release.is_set()
        result = super().synthesize(text, voice, speed, out_path)
        self.synthesized.set()
        return result


async def test_daemon_keeps_source_queued_until_warmup_finishes(tmp_path: Path) -> None:
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-mlx-"))
    engine = GatedWarmupEngine()
    daemon = Daemon(home=tmp_path, engine=engine, sink=FakeSink(), socket_path=socket_dir / "s")
    clip = daemon.store.submit("private source", voice="bm_daniel", speed=1.0)
    await daemon.start()
    try:
        assert await asyncio.to_thread(engine.started.wait, 1)
        await rpc(daemon.socket_path, {"op": "snapshot"})
        queued = daemon.store.get(clip.id)
        assert queued is not None
        assert queued.state is State.QUEUED
        engine.release.set()
        assert await asyncio.to_thread(engine.synthesized.wait, 1)
        assert engine.premature is False
    finally:
        engine.release.set()
        await daemon.stop()
        shutil.rmtree(socket_dir)
