# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Architecture experiments must exercise real declared states and detect violations."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.benchmarks import cases
from scripts.benchmarks.cases import ContractViolationError, cycle, held_cycle, session
from scripts.benchmarks.failures import recovery, rollback
from scripts.benchmarks.pcm import round_trip

from aitts.model import State

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "Benchmark contract: Ready backlog, exact LIFO offsets, "
        "measured interval, rollback and recovery"
    ),
]


async def test_benchmark_backlog_is_ready_playback_work(tmp_path: Path) -> None:
    async with session(tmp_path, backlog=3) as run:
        assert [item.state for item in run.store.playback_queue()].count(State.READY) == 3


@pytest.mark.parametrize("ending", ["played", "skip", "fail"])
async def test_nested_benchmark_has_semantic_witnesses(tmp_path: Path, ending: str) -> None:
    async with session(tmp_path) as run:
        await cycle(run, ending, nested=True)
        assert run.witnesses == 20
        assert len(run.samples["takeover.wall_ms"]) == 2


@pytest.mark.parametrize("microphone", [False, True])
async def test_hold_benchmark_has_semantic_witnesses(tmp_path: Path, *, microphone: bool) -> None:
    async with session(tmp_path) as run:
        await held_cycle(run, microphone=microphone)
        assert run.witnesses == 14


async def test_harness_rejects_lost_resume_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session(tmp_path) as run:
        original = run.sink.start

        def broken_start(path: Path, *, position_ms: int = 0) -> None:
            del position_ms
            original(path, position_ms=0)

        monkeypatch.setattr(run.sink, "start", broken_start)
        with pytest.raises(ContractViolationError, match="exact resumed source offset"):
            await cycle(run)


async def test_measurement_clock_records_known_service_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick = 0

    def clock() -> int:
        return tick

    async with session(tmp_path) as run:
        monkeypatch.setattr(
            cases, "time", SimpleNamespace(perf_counter_ns=clock, process_time_ns=clock)
        )

        async def known_service() -> None:
            nonlocal tick
            tick += 25_000_000

        await run.measure("known", known_service)
        assert run.samples == {
            "known.wall_ms": [25],
            "known.cpu_ms": [25],
            "known.sql_statements": [0],
            "known.commits": [0],
        }


def test_fault_benchmark_witnesses_atomic_rollback(tmp_path: Path) -> None:
    assert rollback(tmp_path)["rollback.witnesses"] == 2


async def test_recovery_benchmark_witnesses_exact_resumption(tmp_path: Path) -> None:
    assert (await recovery(tmp_path))["recovery.witnesses"] == 8


def test_pcm_benchmark_checks_hold_overflow_seek_and_artifact(tmp_path: Path) -> None:
    result = round_trip(tmp_path)
    assert result["witnesses"] == 27
    assert set(result) == {
        "witnesses",
        "producer_while_held.wall_ms",
        "drain.wall_ms",
        "seek.wall_ms",
    }
