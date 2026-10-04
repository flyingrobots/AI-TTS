# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures: a temp store, a fake engine, and a fake audio sink."""

from __future__ import annotations

import asyncio
import os
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

# Tier gates charge process CPU, including user/system time of waited children.
# Wall totals and call p95 remain informational; per-test wall ceilings stay hard.
# Keep the established 10/120/120 budgets while removing runner-contention noise.
_CLASS_BUDGET_SECONDS = {"small": 10.0, "medium": 120.0, "large": 120.0}
_durations: dict[str, list[float]] = {name: [] for name in _SIZE_SECONDS}
_overheads: dict[str, list[float]] = {name: [] for name in _SIZE_SECONDS}
_cpu_durations: dict[str, list[float]] = {name: [] for name in _SIZE_SECONDS}
_suite_started = 0.0


@pytest.fixture(autouse=True)
def isolate_git_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep inherited Git overrides out of each test and its fixture subprocesses.

    Tests exercising Git environment handling may explicitly inject their own
    variables after setup; they must point to owned repositories.
    """
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Start the wall clock the run reports alongside its per-class budgets."""
    del session
    global _suite_started  # noqa: PLW0603 - pytest session hook owns this process timer
    _suite_started = time.perf_counter()
    for samples in (*_durations.values(), *_overheads.values(), *_cpu_durations.values()):
        samples.clear()


def _cpu_seconds() -> float:
    """Count this process and reaped child processes, including kernel CPU work."""
    usage = os.times()
    return usage.user + usage.system + usage.children_user + usage.children_system


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item) -> Iterator[None]:
    """Charge the full setup/call/teardown protocol, even if a phase fails or skips."""
    began = _cpu_seconds()
    try:
        yield
    finally:
        elapsed = _cpu_seconds() - began
        for name in _SIZE_SECONDS:
            if item.get_closest_marker(name) is not None:
                _cpu_durations[name].append(elapsed)
                break


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
    """Report CPU and wall observations; gate only CPU totals and per-test deadlines."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    elapsed = time.perf_counter() - _suite_started
    breaches: list[str] = []
    for name, budget in _CLASS_BUDGET_SECONDS.items():
        samples = _durations[name]
        cpu_samples = _cpu_durations[name]
        if not cpu_samples:
            continue
        wall = sum(samples) + sum(_overheads[name])
        cpu = sum(cpu_samples)
        p95 = _percentile(samples, 0.95) * 1000 if samples else 0
        line = (
            f"{name}: {len(cpu_samples)} tests, CPU {cpu:.2f}s including fixtures and waited "
            f"children, CPU budget {budget:.0f}s; wall {wall:.2f}s, p95 call {p95:.0f}ms"
        )
        if cpu > budget:
            breaches.append(f"{name} tier CPU budget exceeded: {cpu:.2f}s > {budget:.0f}s")
        if reporter is not None:
            reporter.write_line(line, red=cpu > budget)
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
