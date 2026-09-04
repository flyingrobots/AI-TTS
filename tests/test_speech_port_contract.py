# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Real-daemon contract for the public speech application port."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aitts.adapters.unix_socket import UnixSocketSpeechAdapter
from aitts.application.schemas import EnqueueSpeech, SubmissionDisposition
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("approved global-pause admission behavior over the real daemon protocol"),
]


@pytest.fixture
async def daemon(tmp_path: Path) -> Any:
    """Run a hermetic daemon on an owned Unix socket and owned state directory."""
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-port-"))
    service = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(),
        socket_path=socket_dir / "daemon.sock",
    )
    await service.start()
    yield service
    await service.stop()
    shutil.rmtree(socket_dir, ignore_errors=True)


async def test_global_hold_spools_new_speech_through_the_public_port(daemon: Daemon) -> None:
    """Oracle: user-approved rule that playback hold never becomes speech backpressure."""
    speech = UnixSocketSpeechAdapter.connect(daemon.socket_path)

    await asyncio.to_thread(speech.pause_playback)
    receipt = await asyncio.to_thread(
        speech.enqueue_speech,
        EnqueueSpeech(text="spoken after the meeting", source="contract-test"),
    )
    status = await asyncio.to_thread(speech.speech_status)
    queue = await asyncio.to_thread(speech.list_queue)

    assert receipt.accepted is True
    assert receipt.playback_held is True
    assert receipt.submission_disposition is SubmissionDisposition.SPOOLED_UNTIL_RESUME
    assert status.accepting_speech is True
    assert status.playback_held is True
    assert [item.id for item in queue.items] == [receipt.id]
