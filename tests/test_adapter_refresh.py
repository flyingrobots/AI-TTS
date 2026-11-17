# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Runtime identities and explicit refresh preserve usable incumbent models."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.engines.managed import ManagedEngine
from aitts.model_setup import ModelSetupError, RuntimeInstaller, installed_runtime
from tests import test_ipc
from tests.test_ipc import rpc
from tests.test_model_setup import OwnedInstaller, complete_runtime
from tests.test_model_setup_daemon import settled

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

daemon_fixture = test_ipc.python_daemon

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "issue164: adapter identity is reported; only explicit refresh replaces code, never weights"
    ),
]


def contents(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_new_runtime_manifest_identifies_the_copied_adapter(tmp_path: Path) -> None:
    root = OwnedInstaller(tmp_path).install("chatterbox", threading.Event(), lambda _: None)
    manifest = json.loads((root.parent / "chatterbox.json").read_text())
    assert re.fullmatch("[0-9a-f]{64}", manifest.get("adapter_sha256", ""))


async def test_catalog_explicitly_reports_no_private_adapter(daemon_fixture: Daemon) -> None:
    response = await rpc(daemon_fixture.socket_path, {"op": "engines"})
    model = next(row for row in response["models"] if row["name"] == "chatterbox")
    assert model["adapter_status"] is None
    assert model["installed"] is False
    assert daemon_fixture._setup_task is None


async def test_failed_full_repair_does_not_hide_behind_a_ready_incumbent(
    daemon_fixture: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon = daemon_fixture
    old = complete_runtime(daemon._home, "chatterbox")
    incumbent = SilentModel(old)
    daemon._registry.register(incumbent, prepared=True)
    daemon._engines["chatterbox"] = incumbent

    class BrokenModel(SilentModel):
        def warmup(self) -> None:
            raise ModelSetupError

    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: BrokenModel(root))
    await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    await settled(daemon)
    assert daemon._setup_states["chatterbox"]["state"] == "failed"
    installer = OwnedInstaller(daemon._home)
    monkeypatch.setattr(daemon._model_installer, "install", installer.install)
    await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    await settled(daemon)
    failed_root = installed_runtime(daemon._home, "chatterbox")
    assert failed_root != old
    assert daemon._setup_states["chatterbox"]["state"] == "failed"
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: SilentModel(root))
    assert (await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"}))[
        "state"
    ] == "installing"
    await settled(daemon)
    assert installed_runtime(daemon._home, "chatterbox") != failed_root
    assert daemon._setup_states["chatterbox"]["state"] == "ready"


@pytest.mark.parametrize("identity", [None, "invalid", ["0" * 64], 7])
async def test_invalid_legacy_identity_remains_usable_but_unknown(
    daemon_fixture: Daemon, identity: object
) -> None:
    root = complete_runtime(daemon_fixture._home, "chatterbox")
    manifest = root.parent / "chatterbox.json"
    payload = json.loads(manifest.read_text())
    payload["adapter_sha256"] = identity
    manifest.write_text(json.dumps(payload))
    response = await rpc(daemon_fixture.socket_path, {"op": "engines"})
    model = next(row for row in response["models"] if row["name"] == "chatterbox")
    assert model["adapter_status"] == "unknown"
    assert model["installed"] is True


async def test_manifest_identifies_actual_copied_bytes(daemon_fixture: Daemon) -> None:
    class ChangedCopy(OwnedInstaller):
        def run(
            self, arguments: list[str], environment: dict[str, str], cancelled: threading.Event
        ) -> None:
            super().run(arguments, environment, cancelled)
            if "prepare" in arguments:
                worker = Path(arguments[-1]) / "adapter/aitts/model_worker.py"
                worker.write_bytes(worker.read_bytes() + b"\n# altered copy\n")

    ChangedCopy(daemon_fixture._home).install("chatterbox", threading.Event(), lambda _: None)
    response = await rpc(daemon_fixture.socket_path, {"op": "engines"})
    model = next(row for row in response["models"] if row["name"] == "chatterbox")
    assert model["adapter_status"] == "stale"


def runtime_with_identity(home: Path, identity: str) -> Path:
    if identity == "current":
        root = OwnedInstaller(home).install("chatterbox", threading.Event(), lambda _: None)
    else:
        root = complete_runtime(home, "chatterbox")
    manifest = root.parent / "chatterbox.json"
    if identity == "stale":
        payload = json.loads(manifest.read_text())
        payload["adapter_sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload))
    return root


@pytest.mark.parametrize("identity", ["unknown", "stale", "current"])
@pytest.mark.parametrize("operation", ["engines", "snapshot"])
async def test_catalog_reports_identity_without_refreshing(
    daemon_fixture: Daemon, identity: str, operation: str
) -> None:
    daemon = daemon_fixture
    root = runtime_with_identity(daemon._home, identity)
    before = contents(root.parent)
    response = await rpc(daemon.socket_path, {"op": operation})
    model = next(row for row in response["models"] if row["name"] == "chatterbox")
    assert model.get("adapter_status") == identity
    assert model["installed"] is True
    assert daemon._setup_task is None
    assert contents(root.parent) == before


class SilentModel(ManagedEngine):
    def __init__(self, root: Path) -> None:
        super().__init__("chatterbox", root)
        self.closed = False

    def warmup(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@dataclass
class Refreshing:
    daemon: Daemon
    old: Path
    old_bytes: dict[str, str]
    manifest: Path
    old_manifest: bytes
    incumbent: SilentModel
    release: threading.Event


@pytest.fixture
async def refreshing(
    daemon_fixture: Daemon, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Refreshing]:
    daemon = daemon_fixture
    old = complete_runtime(daemon._home, "chatterbox")
    old_bytes = contents(old)
    manifest = old.parent / "chatterbox.json"
    old_manifest = manifest.read_bytes()
    incumbent = SilentModel(old)
    daemon._registry.register(incumbent, prepared=True)
    daemon._engines["chatterbox"] = incumbent
    started, release = threading.Event(), threading.Event()

    class Candidate(SilentModel):
        def warmup(self) -> None:
            started.set()
            if not release.wait(2):
                raise TimeoutError
            if getattr(request, "param", None) == "failure":
                message = "owned warmup failure"
                raise ModelSetupError(message)

    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: Candidate(root))
    if getattr(request, "param", None) == "publication":

        def refuse_publication(_name: str, _root: Path) -> None:
            message = "owned manifest write failure"
            raise OSError(message)

        monkeypatch.setattr(daemon._model_installer, "publish", refuse_publication)
    try:
        response = await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
        assert response == {"ok": True, "state": "installing"}
        assert await asyncio.to_thread(started.wait, 1)
        assert daemon._engines["chatterbox"] is incumbent
        assert incumbent.closed is False
        assert manifest.read_bytes() == old_manifest
        yield Refreshing(daemon, old, old_bytes, manifest, old_manifest, incumbent, release)
    finally:
        release.set()
        if daemon._setup_task is not None:
            await settled(daemon)


async def test_explicit_refresh_publishes_new_code_with_existing_assets(
    refreshing: Refreshing,
) -> None:
    case = refreshing
    case.release.set()
    await settled(case.daemon)
    candidate = case.daemon._engines["chatterbox"]
    assert isinstance(candidate, SilentModel)
    assert candidate.root is not None
    assert candidate.root != case.old
    assert installed_runtime(case.daemon._home, "chatterbox") == candidate.root
    assert (candidate.root / "adapter/aitts/model_worker.py").read_bytes() != (
        case.old / "adapter/aitts/model_worker.py"
    ).read_bytes()
    assert (candidate.root / "assets").resolve() == case.old / "assets"
    assert (candidate.root / "venv").resolve() == case.old / "venv"
    assert contents(case.old) == case.old_bytes
    assert case.incumbent.closed is True


@pytest.mark.parametrize("refreshing", ["failure", "publication"], indirect=True)
async def test_failed_refresh_preserves_manifest_worker_and_weights(refreshing: Refreshing) -> None:
    case = refreshing
    case.release.set()
    await settled(case.daemon)
    assert case.daemon._engines["chatterbox"] is case.incumbent
    assert case.incumbent.closed is False
    assert case.manifest.read_bytes() == case.old_manifest
    assert contents(case.old) == case.old_bytes
    assert list(case.old.parent.glob("chatterbox-*")) == [case.old]
    assert case.daemon._setup_states["chatterbox"]["state"] == "failed"


async def test_cancelled_refresh_preserves_manifest_worker_and_weights(
    refreshing: Refreshing,
) -> None:
    case = refreshing
    assert (await rpc(case.daemon.socket_path, {"op": "cancel_model_setup"}))["ok"] is True
    case.release.set()
    await settled(case.daemon)
    assert case.daemon._engines["chatterbox"] is case.incumbent
    assert case.incumbent.closed is False
    assert case.manifest.read_bytes() == case.old_manifest
    assert contents(case.old) == case.old_bytes
    assert list(case.old.parent.glob("chatterbox-*")) == [case.old]
    assert case.daemon._setup_states["chatterbox"]["state"] == "cancelled"


def test_repeated_refresh_reuses_direct_asset_and_environment_targets(tmp_path: Path) -> None:
    old = complete_runtime(tmp_path, "chatterbox")
    before = contents(old)
    installer = RuntimeInstaller(tmp_path)
    first = installer.refresh("chatterbox", threading.Event(), lambda _: None)
    assert installed_runtime(tmp_path, "chatterbox") == old
    installer.publish("chatterbox", first)
    second = installer.refresh("chatterbox", threading.Event(), lambda _: None)
    assert installed_runtime(tmp_path, "chatterbox") == first
    installer.publish("chatterbox", second)
    assert installed_runtime(tmp_path, "chatterbox") == second
    assert (first / "assets").readlink() == old / "assets"
    assert (second / "assets").readlink() == old / "assets"
    assert (first / "venv").readlink() == old / "venv"
    assert (second / "venv").readlink() == old / "venv"
    assert contents(old) == before
    assert (first / "adapter/aitts").is_dir()
    assert (second / "adapter/aitts").is_dir()


async def test_cancelled_refresh_retries_without_downloading(
    refreshing: Refreshing, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = refreshing

    def refuse_download(_name: str, _cancelled: threading.Event, _progress: object) -> Path:
        message = "refresh must not invoke full installation"
        raise AssertionError(message)

    monkeypatch.setattr(case.daemon._model_installer, "install", refuse_download)
    await rpc(case.daemon.socket_path, {"op": "cancel_model_setup"})
    case.release.set()
    await settled(case.daemon)
    assert case.daemon._setup_states["chatterbox"]["state"] == "cancelled"
    assert (await rpc(case.daemon.socket_path, {"op": "model_setup", "name": "chatterbox"}))[
        "state"
    ] == "installing"
    await settled(case.daemon)
    assert case.daemon._setup_states["chatterbox"]["state"] == "ready"
    assert case.incumbent.closed is True
    assert contents(case.old) == case.old_bytes


def test_refresh_without_usable_runtime_is_refused_without_installing(tmp_path: Path) -> None:
    with pytest.raises(ModelSetupError, match="No usable installed runtime"):
        RuntimeInstaller(tmp_path).refresh("chatterbox", threading.Event(), lambda _: None)
    assert list(tmp_path.iterdir()) == []


def test_refresh_refuses_external_runtime_directory(tmp_path: Path) -> None:
    old = complete_runtime(tmp_path, "chatterbox")
    external = tmp_path / "external-venv"
    (old / "venv").rename(external)
    (old / "venv").symlink_to(external, target_is_directory=True)
    before = contents(tmp_path)
    with pytest.raises(ModelSetupError, match="unsafe environment or asset directory"):
        RuntimeInstaller(tmp_path).refresh("chatterbox", threading.Event(), lambda _: None)
    assert contents(tmp_path) == before
    assert list(old.parent.glob("chatterbox-*")) == [old]
