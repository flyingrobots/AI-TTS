# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Deterministic durability faults and recovery observations at owned boundaries."""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

from aitts.model import State
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from scripts.benchmarks.cases import require, running, session, takeover
from scripts.benchmarks.support import playback_helpers

if TYPE_CHECKING:
    from pathlib import Path

    from tests.support.playback import DeterministicPlaybackSchedule, make_composite_ready, settle
else:
    _support = playback_helpers()
    DeterministicPlaybackSchedule = _support.DeterministicPlaybackSchedule
    make_composite_ready = _support.make_composite_ready
    settle = _support.settle


class CommitFault(sqlite3.Connection):
    """One failed commit, before SQLite commits; never an ambiguous partial fault."""

    fail = False

    def commit(self) -> None:
        """Trip only the armed operation, leaving Store responsible for rollback."""
        if self.fail:
            self.fail = False
            message = "owned commit fault"
            raise sqlite3.OperationalError(message)
        super().commit()


def rollback(root: Path) -> dict[str, float]:
    """Measure failure handling and prove parent/child suspension is atomic."""
    database = root / "rollback.db"
    connection = sqlite3.connect(str(database), factory=CommitFault)
    store = Store(database, connect=lambda _: connection)
    try:
        clip = make_composite_ready(store, "Retained source", ("One", "Two"))
        store.transition(clip.id, State.PLAYING)
        store.transition_segment(clip.id, 0, State.PLAYING)
        before = (store.get(clip.id), store.segments(clip.id))
        connection.fail = True
        began = time.perf_counter_ns()
        try:
            store.suspend_playback(clip.id, 0, 375)
        except sqlite3.OperationalError:
            elapsed = (time.perf_counter_ns() - began) / 1_000_000
        else:
            message = "armed commit fault was not observed"
            raise RuntimeError(message)
        require(
            (store.get(clip.id), store.segments(clip.id)) == before, "failed suspension rolls back"
        )
        reader = Store(database)
        try:
            require(
                (reader.get(clip.id), reader.segments(clip.id)) == before,
                "rollback survives reopen",
            )
        finally:
            reader.close()
        return {"rollback.wall_ms": elapsed, "rollback.witnesses": 2}
    finally:
        store.close()


async def recovery(root: Path) -> dict[str, float]:
    """Recover a coherent SQLite crash image captured during nested playback."""
    image = root / "crash.db"
    async with session(root) as run:
        run.sink.advance_to(375)
        alert = await takeover(run, "First alert")
        run.sink.advance_to(125)
        inner = await takeover(run, "Second alert")
        document = run.document
        # SQLite backup captures durable state without graceful controller shutdown.
        # This is a crash-state experiment, not a torn-sector or power-loss claim.
        with sqlite3.connect(root / "state.db") as source, sqlite3.connect(image) as target:
            source.backup(target)
    store = Store(image)
    try:
        sink = FakeSink()
        schedule = DeterministicPlaybackSchedule()
        began = time.perf_counter_ns()
        store.recover()
        controller = PlaybackController(store, sink, schedule, held=True)
        async with running(controller, schedule):
            require(not sink.started, "recovery must remain silent until user resumes")
            require(controller.current_id == inner.id, "recover highest ranked active alert")
            await controller.resume()
            await settle(controller, schedule)
            await controller.skip()
            await settle(controller, schedule)
            require(controller.current_id == alert.id, "recover intermediate alert before document")
            require(
                sink.start_positions[-1] == 125,  # noqa: PLR2004 - oracle offset
                "recover saved alert offset",
            )
            await controller.skip()
            await settle(controller, schedule)
            require(controller.current_id == document.id, "recover interrupted document")
            require(
                sink.start_positions[-1] == 375,  # noqa: PLR2004 - oracle offset
                "recover saved document offset",
            )
            child = controller.current_segment
            require(child is not None and child.index == 1, "recover document child two")
            require(sink.overlaps == 0, "recovery never overlaps device owners")
            return {
                "recovery.wall_ms": (time.perf_counter_ns() - began) / 1_000_000,
                "recovery.witnesses": 8,
            }
    finally:
        store.close()
