# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Daemon shutdown hands off audio ownership only after device retirement."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.store import Store
from tests.support.playback import make_composite_ready
from tests.test_playback import DelayedReleaseSink, make_ready

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("exclusive playback ownership and durable paused shutdown position"),
]


class ObservedReleaseSink(DelayedReleaseSink):
    """Expose owned device acquisition and outstanding wait calls."""

    def __init__(self) -> None:
        super().__init__()
        self.began = asyncio.Event()
        self.waiters: set[asyncio.Task[object]] = set()

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        super().start(path, position_ms=position_ms)
        self.began.set()

    async def wait(self) -> bool:
        task = asyncio.current_task()
        assert task is not None
        self.waiters.add(task)
        try:
            return await super().wait()
        finally:
            self.waiters.remove(task)


@pytest.mark.parametrize("composite", [False, True], ids=["single-clip", "document"])
async def test_shutdown_retires_device_before_closing_state(
    tmp_path: Path, *, composite: bool
) -> None:
    # Retire only with a stronger calibrated daemon/device handoff contract.
    with tempfile.TemporaryDirectory(prefix="aitts-stop-") as sockets:
        sink = ObservedReleaseSink()
        daemon = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=sink,
            socket_path=Path(sockets) / "d.sock",
            input_activity=FakeInputActivity(),
        )
        item = (
            make_composite_ready(daemon.store, "document", ("first", "second"))
            if composite
            else make_ready(daemon.store, "single clip")
        )
        await daemon.start()
        await daemon.dispatch({"op": "resume"})
        await asyncio.wait_for(sink.began.wait(), timeout=1)
        sink.advance_to(700)
        stop = asyncio.create_task(daemon.stop())
        releasing = asyncio.create_task(sink.stop_requested.wait())
        try:
            async with asyncio.timeout(1):
                await asyncio.wait({stop, releasing}, return_when=asyncio.FIRST_COMPLETED)
            assert (stop.done(), sink.stop_requested.is_set()) == (False, True)
            # State remains available while the device still belongs to this daemon.
            assert daemon.store.get(item.id) is not None
            sink.advance_to(750)
            sink.release_stop()
            await stop
            assert sink.waiters == set()
            recovered = Store(tmp_path / "state.db")
            try:
                parent = recovered.get(item.id)
                assert parent is not None
                assert (parent.state, parent.played_ms) == (State.PAUSED, 750)
                if composite:
                    child = recovered.get_segment(item.id, 0)
                    assert child is not None
                    assert (child.state, child.played_ms) == (State.PAUSED, 750)
            finally:
                recovered.close()
            await daemon.stop()  # Repeated shutdown cannot revisit a closed store.
        finally:
            sink.release_stop()
            await stop
            releasing.cancel()
            await asyncio.gather(releasing, return_exceptions=True)
            # Also clean the deliberately unfixed run's orphaned watcher.
            waiters = list(sink.waiters)
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)


async def test_shutdown_without_resume_preserves_restored_position(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="aitts-stop-held-") as sockets:
        daemon = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=ObservedReleaseSink(),
            socket_path=Path(sockets) / "d.sock",
            input_activity=FakeInputActivity(),
        )
        item = make_ready(daemon.store, "restored clip")
        daemon.store.transition(item.id, State.PLAYING)
        daemon.store.transition(item.id, State.PAUSED, played_ms=400)
        await daemon.start()
        await daemon.stop()
        recovered = Store(tmp_path / "state.db")
        try:
            parent = recovered.get(item.id)
            assert parent is not None
            assert (parent.state, parent.played_ms) == (State.PAUSED, 400)
        finally:
            recovered.close()
