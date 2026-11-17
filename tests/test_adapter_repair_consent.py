# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Cancelled setup catalogs must describe the recovery that the next request performs."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.model_setup import ModelSetupError, installed_runtime
from tests import test_ipc
from tests.test_adapter_refresh import SilentModel, contents
from tests.test_ipc import rpc
from tests.test_model_setup import OwnedInstaller, complete_runtime
from tests.test_model_setup_daemon import settled

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

daemon_fixture = test_ipc.python_daemon
pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "issue164: cancellation cannot promise code-only refresh "
        "while the incumbent requires full repair"
    ),
]


@dataclass
class Repairing:
    daemon: Daemon
    old: Path
    before: dict[str, str]
    manifest: bytes
    incumbent: SilentModel
    failed: bool
    identity: str
    release: threading.Event


@pytest.fixture
async def repairing(
    daemon_fixture: Daemon, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Repairing]:
    daemon = daemon_fixture
    failed, identity = request.param
    old = complete_runtime(daemon._home, "chatterbox")
    manifest = old.parent / "chatterbox.json"
    if identity == "stale":
        payload = json.loads(manifest.read_text())
        payload["adapter_sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload))

    class Broken(SilentModel):
        def warmup(self) -> None:
            raise ModelSetupError

    incumbent = Broken(old) if failed else SilentModel(old)
    daemon._registry.register(incumbent, prepared=not failed)
    daemon._engines["chatterbox"] = incumbent
    if failed:
        with pytest.raises(ModelSetupError):
            daemon._registry.prepare("chatterbox")
    started, release = threading.Event(), threading.Event()

    def hold() -> None:
        started.set()
        if not release.wait(2):
            raise TimeoutError

    class Candidate(SilentModel):
        def warmup(self) -> None:
            hold()

    class Installer(OwnedInstaller):
        def run(
            self, arguments: list[str], environment: dict[str, str], cancelled: threading.Event
        ) -> None:
            super().run(arguments, environment, cancelled)
            if "prepare" in arguments:
                hold()

    installer = Installer(daemon._home)
    monkeypatch.setattr(daemon._model_installer, "install", installer.install)
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: Candidate(root))
    case = Repairing(
        daemon, old, contents(old), manifest.read_bytes(), incumbent, failed, identity, release
    )
    try:
        assert (await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"}))[
            "state"
        ] == "installing"
        assert await asyncio.to_thread(started.wait, 1)
        yield case
    finally:
        release.set()
        await settled(daemon)


@pytest.mark.parametrize(
    "repairing",
    [(failed, identity) for failed in (False, True) for identity in ("unknown", "stale")],
    indirect=True,
)
async def test_cancelled_setup_catalog_matches_the_next_recovery(
    repairing: Repairing, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = repairing
    daemon = case.daemon
    for operation in ("engines", "snapshot"):
        rows = (await rpc(daemon.socket_path, {"op": operation}))["models"]
        assert next(row for row in rows if row["name"] == "chatterbox")["state"] == "installing"
    await rpc(daemon.socket_path, {"op": "cancel_model_setup"})
    case.release.set()
    await settled(daemon)
    assert (case.old.parent / "chatterbox.json").read_bytes() == case.manifest
    assert contents(case.old) == case.before
    assert daemon._engines["chatterbox"] is case.incumbent
    assert case.incumbent.closed is False
    for operation in ("engines", "snapshot"):
        rows = (await rpc(daemon.socket_path, {"op": operation}))["models"]
        model = next(row for row in rows if row["name"] == "chatterbox")
        assert model["state"] == ("failed" if case.failed else "cancelled")
        assert model["message"] == "Setup cancelled. You can retry."
        assert model["installed"] is True
        assert model["adapter_status"] == case.identity
    installer = OwnedInstaller(daemon._home)
    monkeypatch.setattr(daemon._model_installer, "install", installer.install)
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: SilentModel(root))
    await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    await settled(daemon)
    assert bool(installer.arguments) is case.failed
    assert daemon._registry.state("chatterbox") == "ready"
    assert installed_runtime(daemon._home, "chatterbox") != case.old
    assert contents(case.old) == case.before
