# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The shutdown hold added for streaming keeps a microphone hold's durable reason."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aitts.model import State
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from tests.conftest import wait_for
from tests.test_playback import DeterministicPlaybackSchedule, make_ready, start

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "PlaybackController's durable interruption contract: a listener returning to a "
        "restarted daemon must find the microphone hold that silenced it"
    ),
]


async def test_shutdown_keeps_the_reason_for_a_microphone_hold(tmp_path: Path) -> None:
    # Retire only if the interruption reason stops being durable across restarts.
    store = Store(tmp_path / "state.db")
    sink = FakeSink()
    schedule = DeterministicPlaybackSchedule()
    controller = PlaybackController(store, sink, schedule)
    task = await start(controller, schedule)
    try:
        clip = make_ready(store, "a long explanation")
        controller.notify()
        await wait_for(lambda: controller.current_id == clip.id)
        sink.advance_to(400)
        assert await controller.interrupt() is True
        await controller.shutdown()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    try:
        held = store.get_setting("playback_held", "false") == "true"
        restarted = PlaybackController(
            store, FakeSink(), DeterministicPlaybackSchedule(), held=held
        )
        assert restarted.held is True
        assert restarted.interrupted_at is not None, "the restarted daemon lost why it is silent"
        paused = store.get(clip.id)
        assert paused is not None
        assert (paused.state, paused.played_ms) == (State.PAUSED, 400)
    finally:
        store.close()
