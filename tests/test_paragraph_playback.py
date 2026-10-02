# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Paragraph plans reach transport through the daemon's actual admission boundary."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from tests.test_ipc import rpc

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "README paragraph navigation: ordinary paragraphs become durable transport chunks"
    ),
]


class ObservedSink(FakeSink):
    def __init__(self) -> None:
        super().__init__()
        self.started_event = asyncio.Event()

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        super().start(path, position_ms=position_ms)
        self.started_event.set()


async def test_submitted_paragraphs_support_next_and_previous_without_changing_parent(
    tmp_path: Path,
) -> None:
    paragraphs = [" ".join(f"p{p}word{word}" for word in range(50)) for p in range(2)]
    source = "\n\n".join(paragraphs)
    sink = ObservedSink()
    with tempfile.TemporaryDirectory(prefix="tts-para-", dir="/tmp") as folder:
        daemon = Daemon(
            home=tmp_path,
            socket_path=Path(folder) / "s",
            engine=FakeEngine(voices=["v"]),
            sink=sink,
        )
        await daemon.start()
        try:
            accepted = await rpc(
                daemon.socket_path,
                {"op": "submit", "text": source, "voice": "v", "content_format": "plain_text"},
            )
            assert accepted["composite"] is True
            assert accepted["segment_count"] == 2
            await asyncio.wait_for(sink.started_event.wait(), 1)
            parent = daemon.store.get(accepted["id"])
            assert parent is not None
            assert parent.text == source
            assert [child.text for child in daemon.store.segments(parent.id)] == paragraphs
            for operation, expected in [("next_segment", 2), ("previous_segment", 1)]:
                sink.started_event.clear()
                response = await rpc(daemon.socket_path, {"op": operation})
                assert response["ok"] is True
                await asyncio.wait_for(sink.started_event.wait(), 1)
                current = (await rpc(daemon.socket_path, {"op": "status"}))["current"]
                assert current["id"] == parent.id
                assert current["active_segment"]["number"] == expected
                assert current["active_segment"]["text"] == paragraphs[expected - 1]
            assert sink.overlaps == 0
        finally:
            await daemon.stop()
