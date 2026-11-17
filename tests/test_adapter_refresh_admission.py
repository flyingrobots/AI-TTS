# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Code-only setup consent cannot authorize a download after catalog state changes."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.model_setup import ModelSetupError, installed_runtime
from tests import test_ipc
from tests.test_adapter_refresh import SilentModel, contents, runtime_with_identity
from tests.test_ipc import rpc
from tests.test_model_setup import OwnedInstaller
from tests.test_model_setup_daemon import settled

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

daemon_fixture = test_ipc.python_daemon
pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("issue164: explicit code-only consent never permits a full installation"),
]


@pytest.fixture
async def setup_ports(
    daemon_fixture: Daemon, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Daemon, OwnedInstaller]]:
    daemon = daemon_fixture
    installer = OwnedInstaller(daemon._home)
    monkeypatch.setattr(daemon._model_installer, "install", installer.install)
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, root: SilentModel(root))
    try:
        yield daemon, installer
    finally:
        if daemon._setup_task is not None:
            await settled(daemon)


class FallibleModel(SilentModel):
    broken = False

    def warmup(self) -> None:
        if self.broken:
            raise ModelSetupError


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
async def test_refresh_consent_rejects_non_boolean_kinds_before_effects(
    setup_ports: tuple[Daemon, OwnedInstaller], value: object
) -> None:
    daemon, installer = setup_ports
    root = runtime_with_identity(daemon._home, "unknown")
    before = contents(root.parent)
    response = await rpc(
        daemon.socket_path, {"op": "model_setup", "name": "chatterbox", "refresh_only": value}
    )
    assert response == {
        "ok": False,
        "error": {"type": "bad_request", "message": "refresh_only must be a boolean"},
    }
    assert daemon._setup_task is None
    assert installer.arguments == []
    assert contents(root.parent) == before


@pytest.mark.parametrize("changed", ["failed_engine", "failed_setup", "missing"])
async def test_stale_refresh_dialog_is_refused_without_installing(
    setup_ports: tuple[Daemon, OwnedInstaller], monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    daemon, installer = setup_ports
    root = runtime_with_identity(daemon._home, "unknown")
    incumbent = FallibleModel(root)
    daemon._registry.register(incumbent, prepared=True)
    daemon._engines["chatterbox"] = incumbent
    rows = (await rpc(daemon.socket_path, {"op": "engines"}))["models"]
    offered = next(row for row in rows if row["name"] == "chatterbox")
    assert offered["state"] == "ready"
    assert offered["adapter_status"] == "unknown"
    if changed == "missing":
        (root.parent / "chatterbox.json").unlink()
    elif changed == "failed_engine":
        incumbent.broken = True
        with pytest.raises(ModelSetupError):
            daemon._registry.restart("chatterbox")
    else:
        broken = FallibleModel(root)
        broken.broken = True
        monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, _root: broken)
        await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
        await settled(daemon)
    before, states, task = contents(root.parent), dict(daemon._setup_states), daemon._setup_task
    response = await rpc(
        daemon.socket_path, {"op": "model_setup", "name": "chatterbox", "refresh_only": True}
    )
    assert response == {
        "ok": False,
        "error": {
            "type": "illegal_state",
            "message": "Code-only refresh is unavailable. Review full setup before retrying.",
        },
    }
    assert daemon._setup_task is task
    assert daemon._setup_states == states
    assert installer.arguments == []
    assert contents(root.parent) == before
    assert daemon._engines["chatterbox"] is incumbent
    assert incumbent.closed is False


@pytest.mark.parametrize("identity", ["unknown", "stale", "current"])
@pytest.mark.parametrize("ready", [False, True])
async def test_code_only_setup_uses_existing_assets_even_for_a_cold_current_adapter(
    setup_ports: tuple[Daemon, OwnedInstaller], identity: str, *, ready: bool
) -> None:
    daemon, installer = setup_ports
    root = runtime_with_identity(daemon._home, identity)
    before = contents(root)
    if ready:
        incumbent = SilentModel(root)
        daemon._registry.register(incumbent, prepared=True)
        daemon._engines["chatterbox"] = incumbent
    result = await rpc(
        daemon.socket_path, {"op": "model_setup", "name": "chatterbox", "refresh_only": True}
    )
    if ready and identity == "current":
        assert result == {"ok": True, "state": "ready"}
        assert daemon._setup_task is None
    else:
        assert result == {"ok": True, "state": "installing"}
        await settled(daemon)
        assert installed_runtime(daemon._home, "chatterbox") != root
    assert daemon._registry.state("chatterbox") == "ready"
    assert installer.arguments == []
    assert contents(root) == before


@pytest.mark.parametrize("consent", [{}, {"refresh_only": False}])
async def test_legacy_setup_still_authorizes_full_repair(
    setup_ports: tuple[Daemon, OwnedInstaller], consent: dict[str, bool]
) -> None:
    daemon, installer = setup_ports
    root = runtime_with_identity(daemon._home, "unknown")
    incumbent = FallibleModel(root)
    incumbent.broken = True
    daemon._registry.register(incumbent)
    daemon._engines["chatterbox"] = incumbent
    with pytest.raises(ModelSetupError):
        daemon._registry.prepare("chatterbox")
    response = await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox", **consent})
    assert response == {"ok": True, "state": "installing"}
    await settled(daemon)
    assert installer.arguments
    assert daemon._registry.state("chatterbox") == "ready"


async def test_runtime_disappearance_after_refresh_admission_never_falls_back_to_install(
    setup_ports: tuple[Daemon, OwnedInstaller], monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon, installer = setup_ports
    root = runtime_with_identity(daemon._home, "current")
    before = contents(root)
    entered, release = threading.Event(), threading.Event()
    refresh = daemon._model_installer.refresh

    def held(name: str, cancelled: threading.Event, progress: Callable[[str], None]) -> Path:
        entered.set()
        if not release.wait(2):
            raise TimeoutError
        return refresh(name, cancelled, progress)

    monkeypatch.setattr(daemon._model_installer, "refresh", held)
    try:
        result = await rpc(
            daemon.socket_path, {"op": "model_setup", "name": "chatterbox", "refresh_only": True}
        )
        assert result == {"ok": True, "state": "installing"}
        assert await asyncio.to_thread(entered.wait, 1)
        (root.parent / "chatterbox.json").unlink()
    finally:
        release.set()
        await settled(daemon)
    rows = (await rpc(daemon.socket_path, {"op": "engines"}))["models"]
    assert next(row for row in rows if row["name"] == "chatterbox")["state"] == "failed"
    assert installer.arguments == []
    assert contents(root) == before
    assert installed_runtime(daemon._home, "chatterbox") is None
