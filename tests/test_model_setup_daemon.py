# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State, Utterance
from aitts.model_setup import ModelSetupError, SetupCancelledError
from tests import test_ipc
from tests.conftest import wait_for
from tests.test_ipc import rpc
from tests.test_model_setup import complete_runtime

if TYPE_CHECKING:
    from collections.abc import Callable

daemon_fixture = test_ipc.python_daemon

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "setup IPC stays responsive; explicit selection affects only future admissions"
    ),
]


class OwnedModel(FakeEngine):
    name = "chatterbox"
    supported_speeds = (1.0,)

    def __init__(self) -> None:
        super().__init__(["default"])
        self.closed = False

    def close(self) -> None:
        self.closed = True


async def settled(d: Daemon) -> None:
    assert d._setup_task is not None
    await asyncio.wait_for(asyncio.shield(d._setup_task), timeout=3)


async def test_socket_catalog_exposes_absent_models_and_rejects_arbitrary_installs(
    daemon_fixture: Daemon,
) -> None:
    daemon = daemon_fixture
    result = await rpc(daemon.socket_path, {"op": "engines"})
    models = {row["name"]: row for row in result["models"]}
    assert set(models) == {"kokoro", "kokoro-mlx", "chatterbox"}
    assert models["chatterbox"]["state"] == "not installed"
    assert models["chatterbox"]["installed"] is False
    invalid = await rpc(
        daemon.socket_path, {"op": "model_setup", "name": "https://untrusted/model"}
    )
    assert invalid["ok"] is False
    assert daemon._setup_task is None


async def test_download_does_not_block_speech_or_select_model_and_use_changes_future_clips(
    daemon_fixture: Daemon,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = daemon_fixture
    started, release = threading.Event(), threading.Event()
    model = OwnedModel()

    def install(name: str, cancelled: threading.Event, progress: Callable[[str], None]) -> Path:
        del cancelled
        progress("Owned download in progress")
        started.set()
        if not release.wait(2):
            raise TimeoutError
        return complete_runtime(daemon._home, name)

    monkeypatch.setattr(daemon._model_installer, "install", install)
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, _root: model)
    try:
        await rpc(daemon.socket_path, {"op": "pause"})
        result = await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
        assert result == {"ok": True, "state": "installing"}
        assert await asyncio.to_thread(started.wait, 1)
        catalog = await rpc(daemon.socket_path, {"op": "snapshot"})
        assert (
            next(row for row in catalog["models"] if row["name"] == "chatterbox")["message"]
            == "Owned download in progress"
        )
        busy = await rpc(daemon.socket_path, {"op": "model_setup", "name": "kokoro"})
        assert busy["ok"] is False
        before = await rpc(daemon.socket_path, {"op": "submit", "text": "before setup"})
        release.set()
        await settled(daemon)
        assert daemon.engine_name() == "fake"
        after_setup = await rpc(daemon.socket_path, {"op": "submit", "text": "after setup"})
        await rpc(daemon.socket_path, {"op": "settings", "set": {"speed": 1.5}})
        override = await rpc(
            daemon.socket_path,
            {
                "op": "submit",
                "text": "one clip override",
                "engine": "chatterbox",
            },
        )
        assert override["ok"] is True
        assert clip(daemon, override["id"]).speed == 1.0
        assert daemon.engine_name() == "fake"
        assert daemon.store.get_setting("speed", "") == "1.5"
        unsupported = await rpc(
            daemon.socket_path,
            {
                "op": "submit",
                "text": "explicit unsupported speed",
                "engine": "chatterbox",
                "speed": 1.5,
            },
        )
        assert unsupported["ok"] is False
        change = await rpc(daemon.socket_path, {"op": "settings", "set": {"engine": "chatterbox"}})
        assert change["settings"]["voice"] == "default"
        # Merge-up with #65: the saved default speed belongs to other models and is kept;
        # the fixed-speed model speaks default submissions at its supported speed.
        assert change["settings"]["speed"] == 1.5
        selected = await rpc(daemon.socket_path, {"op": "submit", "text": "after selection"})
        assert clip(daemon, selected["id"]).speed == 1.0
        assert clip(daemon, before["id"]).engine == "fake"
        assert clip(daemon, after_setup["id"]).engine == "fake"
        assert clip(daemon, selected["id"]).engine == "chatterbox"
        await wait_for(lambda: clip(daemon, selected["id"]).state is State.READY)
        assert daemon.store.get_setting("engine", "") == "chatterbox"
        assert model.finished == 2
    finally:
        release.set()


@pytest.mark.parametrize("cancel", [True, False])
async def test_cancel_and_failure_preserve_default_and_allow_retry(
    daemon_fixture: Daemon,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cancel: bool,
) -> None:
    daemon = daemon_fixture
    started = threading.Event()

    def install(name: str, cancelled: threading.Event, progress: Callable[[str], None]) -> Path:
        del name, progress
        started.set()
        if cancel:
            if not cancelled.wait(2):
                raise TimeoutError
            raise SetupCancelledError
        message = "owned failure"
        raise ModelSetupError(message)

    monkeypatch.setattr(daemon._model_installer, "install", install)
    await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    assert await asyncio.to_thread(started.wait, 1)
    if cancel:
        assert (await rpc(daemon.socket_path, {"op": "cancel_model_setup"}))["ok"] is True
    await settled(daemon)
    result = await rpc(daemon.socket_path, {"op": "snapshot"})
    row = next(row for row in result["models"] if row["name"] == "chatterbox")
    assert row["state"] == ("cancelled" if cancel else "failed")
    assert row["installed"] is False
    assert daemon.engine_name() == "fake"
    assert "chatterbox" not in daemon._engines
    model = OwnedModel()
    monkeypatch.setattr(
        daemon._model_installer,
        "install",
        lambda name, _cancel, _progress: complete_runtime(daemon._home, name),
    )
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, _root: model)
    assert (await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"}))[
        "ok"
    ] is True
    await settled(daemon)
    assert (
        next(
            row
            for row in (await rpc(daemon.socket_path, {"op": "engines"}))["models"]
            if row["name"] == "chatterbox"
        )["state"]
        == "ready"
    )


def clip(d: Daemon, identifier: str) -> Utterance:
    item = d.store.get(identifier)
    assert item is not None
    return item


@pytest.mark.parametrize(
    "adapter_fields", [{}, {"adapter_sha256": "0" * 64}], ids=["legacy", "stale"]
)
async def test_retry_rebuilds_a_runtime_that_has_complete_assets_but_cannot_load(
    daemon_fixture: Daemon,
    monkeypatch: pytest.MonkeyPatch,
    adapter_fields: dict[str, str],
) -> None:
    from tests.test_model_setup import OwnedInstaller  # noqa: PLC0415

    daemon = daemon_fixture
    old = complete_runtime(daemon._home, "chatterbox")
    manifest = old.parent / "chatterbox.json"
    payload = json.loads(manifest.read_text())
    payload.update(adapter_fields)
    manifest.write_text(json.dumps(payload))

    class BrokenModel(OwnedModel):
        def warmup(self) -> None:
            raise ModelSetupError

    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, _root: BrokenModel())
    await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    await settled(daemon)
    assert daemon._setup_states["chatterbox"]["state"] == "failed"
    installer = OwnedInstaller(daemon._home)
    monkeypatch.setattr(daemon._model_installer, "install", installer.install)
    monkeypatch.setattr("aitts.daemon.managed_engine", lambda _name, _root: OwnedModel())
    await rpc(daemon.socket_path, {"op": "model_setup", "name": "chatterbox"})
    await settled(daemon)
    assert installer.arguments
    assert old.is_dir()
    assert (daemon._home / "model-runtimes/chatterbox.json").read_text().find(old.name) == -1
    assert daemon._setup_states["chatterbox"]["state"] == "ready"
    assert daemon.engine_name() == "fake"


class InProcessKokoro(FakeEngine):
    name = "kokoro"

    def __init__(self) -> None:
        super().__init__(["af_heart"])


async def test_importable_model_package_never_marks_an_uninstalled_runtime_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oracle: issue #116; only a published worker runtime makes a local model installed."""
    import importlib.util  # noqa: PLC0415

    from aitts.application.input_activity import NullInputActivity  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    # Owned import probe: every model package appears importable in the daemon's environment.
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name, *_args: object())
    daemon = Daemon(
        home=tmp_path,
        engine=InProcessKokoro(),
        sink=FakeSink(),
        input_activity=NullInputActivity(),
    )
    rows = {row["name"]: row for row in daemon._model_setup_catalog()}
    assert daemon._registry.state("kokoro") == "cold"
    assert rows["kokoro"]["selected"] is True
    assert rows["kokoro"]["installed"] is False
    assert rows["chatterbox"]["installed"] is False
