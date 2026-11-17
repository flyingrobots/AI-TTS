# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Cancellation joins staged adapter work before discarding its owned candidate."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from tests import test_ipc
from tests.test_adapter_refresh import SilentModel, contents
from tests.test_ipc import rpc
from tests.test_model_setup import complete_runtime
from tests.test_model_setup_daemon import settled

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

daemon_fixture = test_ipc.python_daemon
pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "issue164: cancellation owns and discards staged code while preserving the incumbent"
    ),
]


@dataclass
class Staging:
    daemon: Daemon
    old: Path
    before: dict[str, str]
    incumbent: SilentModel
    release: threading.Event


@pytest.fixture
async def staging(
    daemon_fixture: Daemon, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Staging]:
    daemon = daemon_fixture
    old = complete_runtime(daemon._home, "chatterbox")
    before = contents(old.parent)
    incumbent = SilentModel(old)
    daemon._registry.register(incumbent, prepared=True)
    daemon._engines["chatterbox"] = incumbent
    started, release = threading.Event(), threading.Event()
    refresh = daemon._model_installer.refresh

    def stage(name: str, cancelled: threading.Event, progress: Callable[[str], None]) -> Path:
        root = refresh(name, cancelled, progress)
        started.set()
        if not release.wait(2):
            raise TimeoutError
        return root

    monkeypatch.setattr(daemon._model_installer, "refresh", stage)
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: SilentModel(root))
    try:
        assert (await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"}))[
            "state"
        ] == "installing"
        assert await asyncio.to_thread(started.wait, 1)
        yield Staging(daemon, old, before, incumbent, release)
    finally:
        release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await settled(daemon)


def retained(case: Staging) -> None:
    assert contents(case.old.parent) == case.before
    assert list(case.old.parent.glob("chatterbox-*")) == [case.old]
    assert case.daemon._engines["chatterbox"] is case.incumbent
    assert case.incumbent.closed is False


async def test_cancel_request_discards_the_returned_candidate(staging: Staging) -> None:
    assert (await rpc(staging.daemon.socket_path, {"op": "cancel_model_setup"}))["ok"] is True
    staging.release.set()
    await settled(staging.daemon)
    retained(staging)
    assert staging.daemon._setup_states["chatterbox"]["state"] == "cancelled"


async def test_task_cancellation_joins_and_discards_the_returned_candidate(
    staging: Staging,
) -> None:
    task = staging.daemon._setup_task
    assert task is not None
    task.cancel()
    staging.release.set()
    with pytest.raises(asyncio.CancelledError):
        await settled(staging.daemon)
    retained(staging)
