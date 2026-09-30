# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Restart admission must preserve the listener's explicit-resume boundary."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("architecture section 6: restored playback waits for explicit resume"),
]


@pytest.mark.parametrize("state", [State.READY, State.PLAYING, State.PAUSED])
async def test_restored_playback_engages_global_hold(tmp_path: Path, state: State) -> None:
    # Seed durable pre-crash state; no original worker or device remains alive.
    # Retire only with a replacement calibrated restart-admission contract.
    store = Store(tmp_path / "state.db")
    item = store.submit("restored", voice="v", speed=1)
    store.transition(item.id, State.SYNTHESIZING)
    store.transition(item.id, State.READY, audio_path="restored.wav")
    if state in (State.PLAYING, State.PAUSED):
        store.transition(item.id, State.PLAYING)
    if state is State.PAUSED:
        store.transition(item.id, State.PAUSED)
    store.close()
    with tempfile.TemporaryDirectory(prefix="aitts-recovery-") as sockets:
        daemon = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=FakeSink(),
            socket_path=Path(sockets) / "d.sock",
            input_activity=FakeInputActivity(),
        )
        await daemon.start()
        try:
            status = await daemon.dispatch({"op": "status"})
            assert status["playback_held"] is True
        finally:
            await daemon.stop()
