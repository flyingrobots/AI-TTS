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
_SUITE_BUDGET_SECONDS = 30.0
_suite_started = 0.0


def pytest_sessionstart(session: pytest.Session) -> None:
    """Start the repository's explicit whole-suite latency budget."""
    del session
    global _suite_started  # noqa: PLW0603 - pytest session hook owns this process timer
    _suite_started = time.perf_counter()


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
    """Fail a green suite that exceeds its declared 30-second latency budget."""
    elapsed = time.perf_counter() - _suite_started
    if elapsed <= _SUITE_BUDGET_SECONDS:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            f"suite latency budget exceeded: {elapsed:.2f}s > {_SUITE_BUDGET_SECONDS:.2f}s",
            red=True,
        )
    if exitstatus == int(pytest.ExitCode.OK):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


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
