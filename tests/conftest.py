# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures: a temp store, a fake engine, and a fake audio sink."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from aitts.store import Store

if TYPE_CHECKING:
    from collections.abc import Iterator

_SIZE_SECONDS = {"small": 2, "medium": 15, "large": 30}

# Per-class tier budgets, in seconds of measured test time. Rule 9 budgets by
# class rather than by suite, and for a reason this repository already hit: one
# whole-suite number means every test pays the slowest test's schedule, and it
# can be met by relabelling a slow test rather than fixing it.
#
# These are decay alarms, not targets. Measured on an unloaded machine the
# tiers cost about 1.5s and 12s, so the headroom is roughly six-fold and
# four-fold. That headroom is deliberate: the numbers gate on *test* time, and
# a gate that fires when the machine is busy is a flaky gate, which rule 10
# says does not gate at all. Anything approaching these is real decay, and the
# p95 line printed every run is where it shows up first.
_CLASS_BUDGET_SECONDS = {"small": 10.0, "medium": 45.0, "large": 120.0}
_durations: dict[str, list[float]] = {name: [] for name in _SIZE_SECONDS}
_overheads: dict[str, list[float]] = {name: [] for name in _SIZE_SECONDS}
_suite_started = 0.0


def pytest_sessionstart(session: pytest.Session) -> None:
    """Start the wall clock the run reports alongside its per-class budgets."""
    del session
    global _suite_started  # noqa: PLW0603 - pytest session hook owns this process timer
    _suite_started = time.perf_counter()
    for samples in (*_durations.values(), *_overheads.values()):
        samples.clear()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Attribute each test's own time to its size class.

    Setup and teardown count, not just the call. A fixture that starts a
    daemon costs the same feedback latency as a slow assertion, and charging
    only the call is how a suite gets slow without any test looking slow.
    """
    if report.when == "call":
        samples = _durations
    elif report.when in ("setup", "teardown"):
        samples = _overheads
    else:  # pragma: no cover - pytest defines only these three phases
        return
    for name in _SIZE_SECONDS:
        if name in report.keywords:
            samples[name].append(report.duration)
            return


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Reject tests without one honest size class and one named oracle."""
    violations: list[str] = []
    for item in items:
        sizes = [name for name in _SIZE_SECONDS if item.get_closest_marker(name) is not None]
        if len(sizes) != 1:
            violations.append(f"{item.nodeid}: expected exactly one size marker, found {sizes}")
            continue
        oracle = item.get_closest_marker("oracle")
        valid_oracle = (
            oracle is not None
            and len(oracle.args) == 1
            and isinstance(oracle.args[0], str)
            and bool(oracle.args[0].strip())
        )
        if not valid_oracle:
            violations.append(f"{item.nodeid}: expected oracle('named authority')")
        item.add_marker(pytest.mark.timeout(_SIZE_SECONDS[sizes[0]]))
    if violations:
        details = "\n".join(violations)
        msg = f"testing-standard metadata violations:\n{details}"
        raise pytest.UsageError(msg)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Report per-class latency, and fail a green suite that has decayed."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    elapsed = time.perf_counter() - _suite_started
    breaches: list[str] = []
    for name, budget in _CLASS_BUDGET_SECONDS.items():
        samples = _durations[name]
        if not samples:
            continue
        total = sum(samples) + sum(_overheads[name])
        line = (
            f"{name}: {len(samples)} tests, {total:.2f}s including fixtures, "
            f"p95 call {_percentile(samples, 0.95) * 1000:.0f}ms, budget {budget:.0f}s"
        )
        if total > budget:
            breaches.append(f"{name} tier latency budget exceeded: {total:.2f}s > {budget:.0f}s")
        if reporter is not None:
            reporter.write_line(line, red=total > budget)
    if reporter is not None:
        reporter.write_line(f"wall clock {elapsed:.2f}s")
    if not breaches:
        return
    if reporter is not None:
        for breach in breaches:
            reporter.write_line(breach, red=True)
    if exitstatus == int(pytest.ExitCode.OK):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _percentile(samples: list[float], fraction: float) -> float:
    """The p95 rule 9 asks for, so decay is visible before it is a failure.

    Deliberately not imported from ``aitts.application.metrics``, which has the
    same function: the harness must not depend on the code it is measuring, or
    a defect in that code becomes a mis-reading rather than a failure.
    """
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    st = Store(tmp_path / "state.db")
    yield st
    st.close()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine(voices=["bm_daniel", "af_bella"])


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


async def wait_for(predicate: object, timeout: float = 5.0) -> None:
    """Poll a zero-arg callable until it returns truthy or the timeout expires."""
    assert callable(predicate)
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            msg = "condition not met before timeout"
            raise AssertionError(msg)
        await asyncio.sleep(0.005)
