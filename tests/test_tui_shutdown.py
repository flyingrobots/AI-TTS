# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Deliver daemon results during Textual teardown, with explicit lifecycle gates."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from textual.app import ComposeResult

from aitts.client import DaemonUnreachableError
from aitts.tui.app import NowPlayingCard, SpeechTUI
from aitts.tui.client import AsyncClient

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "Terminal shutdown accepts late daemon results without accessing removed UI"
    ),
]


@pytest.mark.parametrize("delivery", ["progress", "snapshot", "disconnect"])
async def test_daemon_delivery_after_widget_removal_exits_cleanly(  # noqa: C901 - three explicit teardown schedules
    tmp_path: Path, delivery: str
) -> None:
    removed = asyncio.Event()
    send = asyncio.Event()
    snapshot_pending = asyncio.Event()
    consumed = asyncio.Event()
    observed: list[str] = []

    class ClosingCard(NowPlayingCard):
        async def on_unmount(self) -> None:
            # Textual removes children before dispatching their parent's Unmount.
            removed.set()
            await asyncio.wait_for(consumed.wait(), 1)

    class ClosingApp(SpeechTUI):
        def compose(self) -> ComposeResult:
            for widget in super().compose():
                yield ClosingCard() if isinstance(widget, NowPlayingCard) else widget

    class ScheduledClient(AsyncClient):
        requests = 0

        async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
            assert payload["op"] == "snapshot"
            self.requests += 1
            if self.requests == 2:
                snapshot_pending.set()
                await removed.wait()
                observed.append("snapshot")
            return {"status": {"playback_held": False}, "plan": [], "history": []}

        @asynccontextmanager
        async def events(
            self, *, playback_progress: bool = False
        ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
            assert playback_progress

            async def records() -> AsyncGenerator[dict[str, Any]]:
                await send.wait()
                try:
                    if delivery == "snapshot":
                        yield {"event": "changed"}
                    else:
                        await removed.wait()
                        observed.append(delivery)
                        if delivery == "disconnect":
                            message = "Owned shutdown disconnect"
                            raise DaemonUnreachableError(message)
                        yield {"event": "playback_progress", "playback_held": False, "id": None}
                finally:
                    consumed.set()

            async with aclosing(records()) as stream:
                yield stream

    app = ClosingApp(tmp_path / "unused-socket")
    app.client = ScheduledClient(tmp_path / "unused-socket")
    async with app.run_test(size=(80, 24)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 1)
        await pilot.pause()
        send.set()
        if delivery == "snapshot":
            await asyncio.wait_for(snapshot_pending.wait(), 1)
    assert removed.is_set()
    assert consumed.is_set()
    assert observed == [delivery]
