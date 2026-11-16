# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Synthesis-only submissions (`playback: false`) render audio without playing it."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.ipc import ApiError
from aitts.playback import FakeSink

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("submit with playback=False synthesizes WAVs without touching audio sink"),
]


async def test_submit_playback_false_synthesizes_without_playing(tmp_path: Path) -> None:
    sink = FakeSink()
    with tempfile.TemporaryDirectory(prefix="aitts-synth-only-") as sockets:
        daemon = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=sink,
            socket_path=Path(sockets) / "tts.sock",
            input_activity=FakeInputActivity(),
        )
        await daemon.start()
        try:
            reply = await daemon.dispatch(
                {"op": "submit", "text": "Hello remote browser.", "playback": False}
            )
            assert reply["ok"] is True
            assert reply["playback"] is False
            utt_id = reply["id"]

            item: dict[str, object] = {}
            for _ in range(100):
                res = await daemon.dispatch({"op": "get", "id": utt_id})
                item = res["item"]
                if item["state"] == "Ready":
                    break
                await asyncio.sleep(0.02)

            assert item["state"] == "Ready"
            assert item["playback"] is False
            segments = item["segments"]
            assert isinstance(segments, list)
            assert len(segments) == 1
            seg = segments[0]
            assert seg["state"] == "Ready"
            assert seg["audio_ready"] is True
            assert Path(seg["audio_path"]).is_file()
            # CoreAudio sink was never touched and playback queue stays empty.
            assert sink.started == []
            status = await daemon.dispatch({"op": "status"})
            assert status["current"] is None

            cancelled = await daemon.dispatch({"op": "cancel", "id": utt_id})
            assert cancelled["state"] == "Cancelled"
        finally:
            await daemon.stop()


async def test_submit_rejects_non_bool_playback(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="aitts-synth-bad-") as sockets:
        daemon = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=FakeSink(),
            socket_path=Path(sockets) / "tts.sock",
            input_activity=FakeInputActivity(),
        )
        await daemon.start()
        try:
            with pytest.raises(ApiError, match="playback must be a boolean"):
                await daemon.dispatch({"op": "submit", "text": "Hello", "playback": "no"})
        finally:
            await daemon.stop()
