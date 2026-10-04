# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Pilot operates the terminal view against an owned daemon, without audio hardware."""

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from textual.widgets import DataTable, ProgressBar, Static

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink
from aitts.tui.app import SpeechTUI
from aitts.tui.client import AsyncClient
from tests.support.playback import make_composite_ready
from tests.test_ipc import daemon as daemon  # noqa: PLC0414 - shared pytest fixture

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "PROMPTS.md prompt 6: rendered daemon state and Vim transport/queue controls"
    ),
]


async def test_dashboard_renders_literal_queue_and_toggles_global_hold(daemon: Daemon) -> None:
    client = AsyncClient(daemon.socket_path)
    await client.request({"op": "pause"})
    queued = await client.request(
        {"op": "submit", "text": "[red]Literal terminal text[/red]\x1b[2J"}
    )
    app = SpeechTUI(daemon.socket_path)
    async with app.run_test(size=(100, 35)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        table = app.query_one("#queue", DataTable)
        assert table.row_count == 1
        assert str(table.get_row(queued["id"])[-1]) == r"[red]Literal terminal text[/red]\x1b[2J"
        assert "Paused" in str(app.query_one("#now-details", Static).render())
        await pilot.press("space")
        assert (await client.request({"op": "status"}))["playback_held"] is False
        await pilot.press("space")
        assert (await client.request({"op": "status"}))["playback_held"] is True
        await pilot.press("q")
    assert (await client.request({"op": "status"}))["ok"] is True


async def test_vim_selection_reorder_and_double_delete_use_clip_identity(daemon: Daemon) -> None:
    client = AsyncClient(daemon.socket_path)
    await client.request({"op": "pause"})
    first = await client.request({"op": "submit", "text": "First queued text"})
    second = await client.request({"op": "submit", "text": "Second queued text"})
    # A frozen clock keeps every dd pair inside the confirmation window on a slow host.
    app = SpeechTUI(daemon.socket_path, clock=lambda: 0.0)
    async with app.run_test(size=(100, 35)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        # J moves the selected clip down and K moves it up, matching j/k.
        await pilot.press("J")
        plan = (await client.request({"op": "snapshot"}))["plan"]
        assert [item["id"] for item in plan] == [second["id"], first["id"]]
        await pilot.press("K")
        plan = (await client.request({"op": "snapshot"}))["plan"]
        assert [item["id"] for item in plan] == [first["id"], second["id"]]
        await pilot.press("J", "j")
        assert app.query_one("#queue", DataTable).cursor_row == 1
        await pilot.press("k")
        assert app.query_one("#queue", DataTable).cursor_row == 0
        await pilot.press("d")
        assert len((await client.request({"op": "snapshot"}))["plan"]) == 2
        await pilot.press("j", "k", "d")
        assert len((await client.request({"op": "snapshot"}))["plan"]) == 2
        await pilot.press("d")
        plan = (await client.request({"op": "snapshot"}))["plan"]
        assert [item["id"] for item in plan] == [first["id"]]


@pytest.mark.oracle("docs/testing-evidence/2026-09-30-terminal-dashboard.md: dd within one second")
async def test_double_delete_expires_after_the_confirmation_window(daemon: Daemon) -> None:
    client = AsyncClient(daemon.socket_path)
    await client.request({"op": "pause"})
    queued = await client.request({"op": "submit", "text": "Stays queued"})
    now = [100.0]
    app = SpeechTUI(daemon.socket_path, clock=lambda: now[0])
    async with app.run_test(size=(100, 35)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        await pilot.press("d")
        now[0] += 1.0
        await pilot.press("d")
        plan = (await client.request({"op": "snapshot"}))["plan"]
        assert [item["id"] for item in plan] == [queued["id"]], "a late second d cancelled"
        now[0] += 0.999
        await pilot.press("d")
        assert (await client.request({"op": "snapshot"}))["plan"] == []


async def test_external_idle_pause_updates_the_dashboard(daemon: Daemon) -> None:
    app = SpeechTUI(daemon.socket_path)
    async with app.run_test(size=(100, 35)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        app.updated.clear()
        await AsyncClient(daemon.socket_path).request({"op": "pause"})
        await asyncio.wait_for(app.updated.wait(), 1)
        assert app.snapshot["status"]["playback_held"] is True
        assert "Paused" in str(app.query_one("#now-details", Static).render())


class ObservedSink(FakeSink):
    def __init__(self) -> None:
        super().__init__()
        self.started_event = asyncio.Event()

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        super().start(path, position_ms=position_ms)
        self.started_event.set()


@pytest.fixture
async def controlled_daemon(tmp_path: Path) -> AsyncIterator[tuple[Daemon, ObservedSink]]:
    with tempfile.TemporaryDirectory(prefix="tui-play-", dir="/tmp") as folder:
        sink = ObservedSink()
        daemon = Daemon(
            home=tmp_path,
            socket_path=Path(folder) / "s",
            engine=FakeEngine(voices=["v"]),
            sink=sink,
        )
        await daemon.start()
        try:
            yield daemon, sink
        finally:
            await daemon.stop()


async def test_chunk_restart_skip_and_history_replay_keys(
    controlled_daemon: tuple[Daemon, ObservedSink],
) -> None:
    daemon, sink = controlled_daemon
    document = make_composite_ready(
        daemon.store, "Complete source", ("First spoken chunk", "Second spoken chunk")
    )
    await asyncio.wait_for(sink.started_event.wait(), 1)
    client = AsyncClient(daemon.socket_path)
    app = SpeechTUI(daemon.socket_path)
    async with app.run_test(size=(100, 35)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        assert "Chunk 1/2" in str(app.query_one("#now-details", Static).render())
        await pilot.press("n")
        assert (await client.request({"op": "status"}))["current"]["active_segment"]["number"] == 2
        assert "Second spoken chunk" in str(app.query_one("#spoken-text", Static).render())
        await pilot.press("p")
        assert (await client.request({"op": "status"}))["current"]["active_segment"]["number"] == 1
        sink.advance_to(400)
        starts = len(sink.started)
        await pilot.press("r")
        assert len(sink.started) == starts + 1
        assert (await client.request({"op": "status"}))["current"]["position_ms"] == 0
        await pilot.press("s")
        skipped = daemon.store.get(document.id)
        assert skipped is not None
        assert skipped.state is State.SKIPPED
        history = app.query_one("#history", DataTable)
        assert history.row_count == 1
        await pilot.press("tab")
        assert app.focused is history
        sink.started_event.clear()
        await pilot.press("enter")
        await asyncio.wait_for(sink.started_event.wait(), 1)
        current = (await client.request({"op": "status"}))["current"]
        assert current["id"] != document.id
        assert current["text"] == document.text
        assert current["voice"] == document.voice


async def test_dashboard_reconnects_when_daemon_appears(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="tui-reconnect-", dir="/tmp") as folder:
        socket = Path(folder) / "s"
        app = SpeechTUI(socket)
        daemon = Daemon(
            home=tmp_path, socket_path=socket, engine=FakeEngine(voices=["v"]), sink=FakeSink()
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert bool(app.connected) is False
            assert "Disconnected" in str(app.query_one("#connection", Static).render())
            await daemon.start()
            try:
                await asyncio.wait_for(app.updated.wait(), 2)
                await pilot.pause()
                assert app.connected is True
                assert "Connected" in str(app.query_one("#connection", Static).render())
            finally:
                await daemon.stop()


async def test_unknown_live_duration_does_not_invent_a_completion_percentage(
    controlled_daemon: tuple[Daemon, ObservedSink],
) -> None:
    daemon, sink = controlled_daemon
    clip = daemon.store.submit("Still generating this clip", voice="v", speed=1.0)
    daemon.store.transition(clip.id, State.SYNTHESIZING)
    daemon.store.transition(clip.id, State.READY, audio_path="/owned/streaming.wav")
    await asyncio.wait_for(sink.started_event.wait(), 1)
    sink.advance_to(400)
    app = SpeechTUI(daemon.socket_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        assert app.query_one("#progress", ProgressBar).total is None
        assert "--:--" in str(app.query_one("#now-details", Static).render())
