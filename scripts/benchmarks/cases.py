# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Owned playback/SQLite experiments with exact semantic outcome oracles."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aitts.model import Priority, State, Utterance
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from scripts.benchmarks.support import playback_helpers

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path


if TYPE_CHECKING:
    from tests.support.playback import DeterministicPlaybackSchedule, make_composite_ready, settle
else:
    _support = playback_helpers()
    DeterministicPlaybackSchedule = _support.DeterministicPlaybackSchedule
    make_composite_ready = _support.make_composite_ready
    settle = _support.settle


class ContractViolationError(RuntimeError):
    """A benchmark observed a behavior outside its declared oracle."""


def require(condition: bool, contract: str) -> None:  # noqa: FBT001 - named invariant boundary
    """Never turn a failed correctness witness into a latency sample."""
    if not condition:
        raise ContractViolationError(contract)


@dataclass
class DatabaseProbe:
    """Count SQLite boundary work without retaining SQL or source text."""

    statements: int = 0
    commits: int = 0

    def trace(self, sql: str) -> None:
        """Observe SQLite statements through its supported trace callback."""
        self.statements += 1
        self.commits += sql == "COMMIT"

    def connect(self, database: str) -> sqlite3.Connection:
        """Supply the Store's existing connection-factory port."""
        connection = sqlite3.connect(database)
        connection.set_trace_callback(self.trace)
        return connection


@dataclass
class Session:
    """A real controller and file-backed WAL Store with a contract FakeSink."""

    store: Store
    sink: FakeSink
    controller: PlaybackController
    schedule: DeterministicPlaybackSchedule
    document: Utterance
    probe: DatabaseProbe
    task: asyncio.Task[None]
    samples: dict[str, list[float]] = field(default_factory=dict)
    witnesses: int = 0

    async def turn(self) -> None:
        """Wait for a controller planning boundary, never a scheduling sleep."""
        await settle(self.controller, self.schedule)

    def expect(self, clip: Utterance, offset: int, child: int | None = None) -> None:
        """Observe ownership, exact sink offset and child at public boundaries."""
        segment = self.controller.current_segment
        require(self.controller.current_id == clip.id, "current clip identity")
        require(self.sink.start_positions[-1] == offset, "exact resumed source offset")
        require((segment.index if segment else None) == child, "exact resumed child index")
        require(self.sink.overlaps == 0, "single audio device owner")
        self.witnesses += 4

    def alert(self, text: str = "Controlled alert") -> Utterance:
        """Prepare a Ready preempt without claiming model inference is measured."""
        clip = self.store.submit(
            text, voice="v", speed=1.0, priority=Priority.PREEMPT, at_head=True
        )
        self.store.transition(clip.id, State.SYNTHESIZING)
        return self.store.transition(
            clip.id, State.READY, audio_path=f"/owned/{clip.id}.wav", duration_ms=1000
        )

    async def measure(self, name: str, operation: Callable[[], Awaitable[None]]) -> None:
        """Measure a completed operation including its controller convergence witness."""
        statements, commits = self.probe.statements, self.probe.commits
        cpu = time.process_time_ns()
        began = time.perf_counter_ns()
        await operation()
        elapsed = (time.perf_counter_ns() - began) / 1_000_000
        self.samples.setdefault(name + ".wall_ms", []).append(elapsed)
        self.samples.setdefault(name + ".cpu_ms", []).append(
            (time.process_time_ns() - cpu) / 1_000_000
        )
        self.samples.setdefault(name + ".sql_statements", []).append(
            self.probe.statements - statements
        )
        self.samples.setdefault(name + ".commits", []).append(self.probe.commits - commits)


@contextlib.asynccontextmanager
async def session(root: Path, backlog: int = 0) -> AsyncIterator[Session]:
    """Start on document chunk two, with independently prepared pending backlog."""
    probe = DatabaseProbe()
    store = Store(root / "state.db", connect=probe.connect)
    try:
        sink = FakeSink()
        schedule = DeterministicPlaybackSchedule()
        document = make_composite_ready(store, "Original source", ("First chunk", "Second chunk"))
        for index in range(backlog):
            queued = store.submit(f"Pending source {index}", voice="v", speed=1.0)
            store.transition(queued.id, State.SYNTHESIZING)
            store.transition(
                queued.id, State.READY, audio_path=f"/owned/{queued.id}.wav", duration_ms=1000
            )
        controller = PlaybackController(store, sink, schedule)
        async with running(controller, schedule) as task:
            instance = Session(store, sink, controller, schedule, document, probe, task)
            sink.finish_current()
            await schedule.wait_for_idle_after(schedule.idle_cycles)
            sink.advance_to(375)
            instance.expect(document, 0, 1)
            yield instance
    finally:
        store.close()


@contextlib.asynccontextmanager
async def running(
    controller: PlaybackController, schedule: DeterministicPlaybackSchedule
) -> AsyncIterator[asyncio.Task[None]]:
    """Own the controller task from creation, so a failed start still stops and awaits it."""
    idle_before = schedule.idle_cycles
    task = asyncio.create_task(controller.run())
    try:
        await schedule.wait_for_idle_after(idle_before)
        yield task
    finally:
        await controller.shutdown()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def takeover(run: Session, name: str) -> Utterance:
    """Record Ready-to-settled takeover, excluding preparation/inference."""
    alert = run.alert(name)
    await run.measure("takeover", run.turn)
    run.expect(alert, 0)
    return alert


async def terminal(run: Session, ending: str) -> None:
    """Resolve the urgent clip through each supported terminal outcome."""

    async def finish() -> None:
        if ending == "skip":
            await run.controller.skip()
            await run.turn()
        else:
            cycle = run.schedule.idle_cycles
            if ending == "fail":
                run.sink.fail_current("Owned benchmark device failure")
            else:
                run.sink.finish_current()
            await run.schedule.wait_for_idle_after(cycle)
            await run.turn()

    await run.measure("resume_after_" + ending, finish)


async def cycle(run: Session, ending: str = "played", *, nested: bool = False) -> None:
    """Exercise nested/terminal preemption with bounded fixture retention."""
    run.sink.advance_to(375)
    alert = await takeover(run, "First alert")
    if nested:
        run.sink.advance_to(125)
        inner = await takeover(run, "Nested alert")
        await terminal(run, ending)
        run.expect(alert, 125)
        run.store.remove_history(inner.id)
    await terminal(run, ending)
    run.expect(run.document, 375, 1)
    run.store.remove_history(alert.id)
    # FakeSink records starts for tests; do not mistake retained fixture history
    # for a leak in the real output adapter during long-running experiments.
    run.sink.started[:] = run.sink.started[-1:]
    run.sink.start_positions[:] = run.sink.start_positions[-1:]


async def held_cycle(run: Session, *, microphone: bool) -> None:
    """Preserve a held clip until explicit resume."""
    run.sink.advance_to(375)
    if microphone:
        require(await run.controller.interrupt(), "microphone interruption accepted")
    else:
        await run.controller.pause()
    alert = run.alert()
    await run.turn()
    require(run.controller.current_id == run.document.id, "global hold defeats preemption")
    require(run.controller.held, "hold remains authoritative")
    run.witnesses += 2

    async def resume() -> None:
        await run.controller.resume()
        await run.turn()

    await run.measure("held_resume", resume)
    run.expect(alert, 0)
    await terminal(run, "skip")
    run.expect(run.document, 375, 1)
    run.store.remove_history(alert.id)
