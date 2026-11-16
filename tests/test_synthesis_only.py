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
from aitts.model import State
from aitts.playback import FakeSink
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("submit with playback=False synthesizes WAVs without touching audio sink"),
]


@pytest.mark.parametrize(
    ("text", "count"),
    [("Hello remote browser.", 1), ("# First\n\nHello.\n\n# Second\n\nGoodbye.", 2)],
)
async def test_submit_playback_false_synthesizes_without_playing(
    tmp_path: Path, text: str, count: int
) -> None:
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
                {"op": "submit", "text": text, "content_format": "markdown", "playback": False}
            )
            assert reply["ok"] is True
            assert reply["playback"] is False
            utt_id = reply["id"]

            item: dict[str, object] = {}
            for _ in range(100):
                res = await daemon.dispatch({"op": "get", "id": utt_id})
                item = res["item"]
                if item["state"] == "Ready" and all(
                    segment["audio_ready"] for segment in res["item"].get("segments", [])
                ):
                    break
                await asyncio.sleep(0.02)

            assert item["state"] == "Ready"
            assert item["playback"] is False
            segments = item["segments"]
            assert isinstance(segments, list)
            assert len(segments) == count
            assert [seg["index"] for seg in segments] == list(range(count))
            for seg in segments:
                assert seg["state"] == "Ready"
                assert seg["audio_ready"] is True
                assert Path(seg["audio_path"]).is_file()
            # CoreAudio sink was never touched and playback queue stays empty.
            assert sink.started == []
            status = await daemon.dispatch({"op": "status"})
            assert status["current"] is None
            assert status["version"] == "0.2.0"

            cancelled = await daemon.dispatch({"op": "cancel", "id": utt_id})
            assert cancelled["state"] == "Cancelled"
        finally:
            await daemon.stop()


def test_restart_preserves_synthesis_only_exclusion_without_blocking_playback(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.db"
    store = Store(database)
    remote = store.submit("Remote", voice="v", speed=1.0, playback=False)
    local = store.submit("Local", voice="v", speed=1.0)
    for item in (remote, local):
        store.transition(item.id, State.SYNTHESIZING)
        store.transition(item.id, State.READY, audio_path="fixture.wav", duration_ms=1)
    store.close()

    restarted = Store(database)
    try:
        restarted.recover()
        restored = restarted.get(remote.id)
        assert restored is not None
        assert restored.playback is False
        assert [item.id for item in restarted.playback_queue()] == [local.id]
        pending = restarted.next_pending()
        assert pending is not None
        assert pending.id == local.id
    finally:
        restarted.close()


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
