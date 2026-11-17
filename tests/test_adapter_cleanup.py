# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Failed setup cleanup must retain custody and let unrelated synthesis resume."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.model import State
from tests import test_ipc
from tests.conftest import wait_for
from tests.test_adapter_refresh import SilentModel, contents
from tests.test_ipc import rpc
from tests.test_model_setup import OwnedInstaller, complete_runtime
from tests.test_model_setup_daemon import clip, settled

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

daemon_fixture = test_ipc.python_daemon
pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "issue164: cleanup failure restores synthesis, preserves cause "
        "and retains uncertain custody"
    ),
]


class CleanupScenario:
    def __init__(self, daemon: Daemon, fault: str, *, interrupted: bool) -> None:
        self.daemon, self.fault, self.interrupted = daemon, fault, interrupted
        self.old = complete_runtime(daemon._home, "chatterbox")
        self.before = contents(self.old)
        self.manifest = (self.old.parent / "chatterbox.json").read_bytes()
        self.incumbent = SilentModel(self.old)
        daemon._registry.register(self.incumbent, prepared=True)
        daemon._engines["chatterbox"] = self.incumbent
        self.fail_cleanup = True
        self.candidates: list[SilentModel] = []
        self.started, self.release = threading.Event(), threading.Event()
        self.real_remove, self.real_synthesize = shutil.rmtree, daemon._engine.synthesize

    def candidate(self, _name: str, root: Path) -> Candidate:
        worker = Candidate(root, self)
        self.candidates.append(worker)
        return worker

    def remove(self, root: Path) -> None:
        if self.fault == "remove" and self.fail_cleanup and root.parent == self.old.parent:
            message = "owned cleanup failure"
            raise OSError(message)
        self.real_remove(root)

    def synthesize(self, text: str, voice: str, speed: float, target: Path) -> int:
        self.started.set()
        if not self.release.wait(2):
            raise TimeoutError
        return self.real_synthesize(text, voice, speed, target)

    @staticmethod
    def publication(_name: str, _root: Path) -> None:
        message = "owned publication failure"
        raise OSError(message)


class Candidate(SilentModel):
    def __init__(self, root: Path, case: CleanupScenario) -> None:
        super().__init__(root)
        self.case = case

    def close(self) -> None:
        if self.case.fault == "close" and self.case.fail_cleanup:
            message = "owned cleanup failure"
            raise OSError(message)
        super().close()


@pytest.fixture
async def cleanup(
    daemon_fixture: Daemon, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[CleanupScenario]:
    fault, interrupted = request.param
    case = CleanupScenario(daemon_fixture, fault, interrupted=interrupted)
    daemon = case.daemon
    with monkeypatch.context() as patch:
        patch.setattr("aitts.daemon.managed_engine", case.candidate)
        patch.setattr(daemon._model_installer, "publish", case.publication)
        patch.setattr(daemon._model_installer, "install", OwnedInstaller(daemon._home).install)
        patch.setattr("aitts.daemon.shutil.rmtree", case.remove)
        if interrupted:
            patch.setattr(daemon._engine, "synthesize", case.synthesize)
        try:
            yield case
        finally:
            case.release.set()
            case.fail_cleanup = False
            if daemon._setup_task is not None:
                with contextlib.suppress(asyncio.CancelledError, OSError):
                    await settled(daemon)


async def assert_retained_worker_blocks_setup(daemon: Daemon, worker: SilentModel) -> None:
    task = daemon._setup_task
    refused = await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    assert refused == {
        "ok": False,
        "error": {
            "type": "illegal_state",
            "message": "A setup worker could not close. Restart AI-TTS before retrying.",
        },
    }
    assert daemon._setup_worker is worker
    assert daemon._setup_task is task


@pytest.mark.parametrize(
    "cleanup",
    [(fault, cancel) for fault in ("close", "remove") for cancel in (False, True)],
    indirect=True,
)
async def test_cleanup_failure_preserves_custody_and_resumes_speech(
    cleanup: CleanupScenario,
) -> None:
    case, daemon = cleanup, cleanup.daemon
    pool = daemon._pool
    assert pool is not None
    await rpc(daemon.socket_path, {"op": "pause"})
    if case.interrupted:
        await rpc(daemon.socket_path, {"op": "submit", "text": "in flight"})
        assert await asyncio.to_thread(case.started.wait, 1)
    assert (await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"}))[
        "state"
    ] == "installing"
    if case.interrupted:
        await wait_for(lambda: not pool.enabled.is_set())
        assert daemon._setup_task is not None
        daemon._setup_task.cancel()
    task = daemon._setup_task
    assert task is not None
    with pytest.raises(asyncio.CancelledError if case.interrupted else OSError) as raised:
        await asyncio.wait_for(task, timeout=3)
    assert pool.enabled.is_set()
    assert isinstance(raised.value.__cause__, OSError)
    if case.interrupted:
        assert str(raised.value.__cause__) == "owned cleanup failure"
    else:
        assert str(raised.value) == "owned cleanup failure"
        assert str(raised.value.__cause__) == "owned publication failure"
    assert len(case.candidates) == 1
    worker = case.candidates[0]
    assert worker.root is not None
    assert worker.root.exists()
    assert daemon._setup_worker is (worker if case.fault == "close" else None)
    assert daemon._engines["chatterbox"] is case.incumbent
    assert case.incumbent.closed is False
    assert contents(case.old) == case.before
    assert (case.old.parent / "chatterbox.json").read_bytes() == case.manifest
    rows = (await rpc(daemon.socket_path, {"op": "engines"}))["models"]
    model = next(row for row in rows if row["name"] == "chatterbox")
    assert model["state"] == "failed"
    assert model["message"] == "Setup cleanup failed. Restart AI-TTS before retrying."
    if case.fault == "close":
        await assert_retained_worker_blocks_setup(daemon, worker)
    case.release.set()
    queued = await rpc(daemon.socket_path, {"op": "submit", "text": "after cleanup failure"})
    await wait_for(lambda: clip(daemon, queued["id"]).state == State.READY)
