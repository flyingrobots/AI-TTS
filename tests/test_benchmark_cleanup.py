# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A benchmark session that fails while starting still releases its controller and Store."""

import asyncio
from pathlib import Path

import pytest
from scripts.benchmarks import cases, failures

from aitts.store import Store
from tests.support.playback import DeterministicPlaybackSchedule

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("Startup failure: no pending controller task and every opened Store closed"),
]


class StartupFailureError(RuntimeError):
    """The owned fault injected while the controller reaches its first idle boundary."""


class FailingSchedule(DeterministicPlaybackSchedule):
    async def wait_for_idle_after(self, cycle: int) -> None:
        del cycle
        raise StartupFailureError


class TrackedStore(Store):
    opened: list["TrackedStore"] = []  # noqa: RUF012 - per-test registry reset below

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.closed = False
        TrackedStore.opened.append(self)

    def close(self) -> None:
        self.closed = True
        super().close()


def leaked_tasks() -> list[asyncio.Task[object]]:
    current = asyncio.current_task()
    return [task for task in asyncio.all_tasks() if task is not current and not task.done()]


@pytest.fixture(autouse=True)
def tracked_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    TrackedStore.opened = []
    monkeypatch.setattr(cases, "Store", TrackedStore)
    monkeypatch.setattr(failures, "Store", TrackedStore)


async def test_session_startup_failure_releases_controller_and_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cases, "DeterministicPlaybackSchedule", FailingSchedule)
    with pytest.raises(StartupFailureError):
        async with cases.session(tmp_path):
            pytest.fail("a session whose controller never started must not be yielded")
    await asyncio.sleep(0)
    assert leaked_tasks() == []
    assert [store.closed for store in TrackedStore.opened] == [True]


async def test_recovery_startup_failure_releases_controller_and_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(failures, "DeterministicPlaybackSchedule", FailingSchedule)
    with pytest.raises(StartupFailureError):
        await failures.recovery(tmp_path)
    await asyncio.sleep(0)
    assert leaked_tasks() == []
    assert [store.closed for store in TrackedStore.opened] == [True, True]
