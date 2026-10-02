# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import threading
from pathlib import Path

import pytest

from aitts.engines.selection import configured_engines
from aitts.model_catalog import MODELS
from aitts.model_setup import (
    ModelSetupError,
    RuntimeInstaller,
    SetupCancelledError,
    installed_runtime,
)
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "guided setup publishes only complete checked runtimes; cancellation preserves incumbent"
    ),
]


def complete_runtime(home: Path, name: str) -> Path:
    root = home / "model-runtimes" / f"{name}-fixture"
    (root / "venv/bin").mkdir(parents=True)
    (root / "venv/bin/python").symlink_to(sys.executable)
    (root / "adapter/aitts").mkdir(parents=True)
    (root / "adapter/aitts/model_worker.py").write_text("# owned fixture")
    for filename in MODELS[name].files:
        file = root / "assets" / filename
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"owned fixture")
    (root.parent / f"{name}.json").write_text(
        json.dumps(
            {
                "directory": root.name,
                "revision": MODELS[name].revision,
                "worker_protocol": 1,
            }
        )
    )
    return root


class OwnedInstaller(RuntimeInstaller):
    def __init__(self, home: Path, failure: str | None = None) -> None:
        super().__init__(home)
        self.failure = failure
        self.arguments: list[list[str]] = []

    def run(
        self, arguments: list[str], environment: dict[str, str], cancelled: threading.Event
    ) -> None:
        del environment
        self.arguments.append(arguments)
        if arguments[1] == "venv":
            root = Path(arguments[-1])
            (root / "bin").mkdir(parents=True)
            (root / "bin/python").symlink_to(sys.executable)
        elif "prepare" in arguments:
            if self.failure == "failure":
                message = "injected download failure"
                raise ModelSetupError(message)
            root = Path(arguments[-1])
            for filename in MODELS[arguments[-2]].files:
                file = root / "assets" / filename
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"owned model asset")
            if self.failure == "cancel":
                cancelled.set()


@pytest.mark.parametrize("outcome", ["failure", "cancel"])
def test_failed_or_cancelled_candidate_preserves_incumbent(tmp_path: Path, outcome: str) -> None:
    incumbent = complete_runtime(tmp_path, "kokoro")
    manifest = (incumbent.parent / "kokoro.json").read_bytes()
    installer = OwnedInstaller(tmp_path, outcome)
    with pytest.raises(SetupCancelledError if outcome == "cancel" else ModelSetupError):
        installer.install("kokoro", threading.Event(), lambda _: None)
    assert installed_runtime(tmp_path, "kokoro") == incumbent
    assert (incumbent.parent / "kokoro.json").read_bytes() == manifest
    assert list(incumbent.parent.glob("kokoro-*")) == [incumbent]


def test_success_publishes_private_complete_runtime_without_mutating_daemon(tmp_path: Path) -> None:
    installer = OwnedInstaller(tmp_path)
    phases: list[str] = []
    root = installer.install("kokoro", threading.Event(), phases.append)
    assert installed_runtime(tmp_path, "kokoro") == root
    assert phases == ["Installing runtime", "Downloading and checking model"]
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root.parent / "kokoro.json").stat().st_mode) == 0o600
    pip = installer.arguments[1]
    assert pip[:3] == [shutil.which("uv"), "pip", "install"]
    assert pip[3:5] == ["--python", str(root / "venv/bin/python")]
    assert "--require-hashes" in pip
    assert "--requirements" in pip
    assert Path(pip[-1]).is_file()
    assert (root / "adapter/aitts/model_worker.py").is_file()
    assert "--python" in installer.arguments[0]
    assert "3.12" in installer.arguments[0]


@pytest.mark.parametrize(
    "corruption", ["revision", "protocol", "traversal", "asset", "worker", "symlink"]
)
def test_incomplete_or_unsafe_manifests_are_not_discovered(tmp_path: Path, corruption: str) -> None:
    root = complete_runtime(tmp_path, "chatterbox")
    manifest = root.parent / "chatterbox.json"
    payload = json.loads(manifest.read_text())
    if corruption == "revision":
        payload["revision"] = "unknown revision"
    elif corruption == "protocol":
        payload["worker_protocol"] = 999
    elif corruption == "traversal":
        payload["directory"] = "chatterbox-fixture/../chatterbox-fixture"
    elif corruption == "asset":
        (root / "assets/conds.pt").unlink()
    elif corruption == "worker":
        (root / "adapter/aitts/model_worker.py").unlink()
    else:
        manifest.rename(root.parent / "outside.json")
        manifest.symlink_to(root.parent / "outside.json")
    if corruption in {"revision", "protocol", "traversal"}:
        manifest.write_text(json.dumps(payload))
    assert installed_runtime(tmp_path, "chatterbox") is None


def test_managed_model_selection_survives_restart_without_optional_daemon_packages(
    tmp_path: Path,
) -> None:
    root = complete_runtime(tmp_path, "kokoro-mlx")
    selected, engines = configured_engines(tmp_path, override="kokoro-mlx", probe_mlx=lambda: False)
    assert selected.name == "kokoro-mlx"
    assert selected.root == root  # type: ignore[attr-defined]
    assert set(engines) == {"kokoro", "kokoro-mlx"}


def test_installer_failure_keeps_diagnostics_private_and_bounded(tmp_path: Path) -> None:
    (tmp_path / "model-runtimes").mkdir()
    with pytest.raises(ModelSetupError):
        RuntimeInstaller(tmp_path).run(
            [sys.executable, "-c", "import sys; print('x' * 100000); sys.exit(1)"],
            {},
            threading.Event(),
        )
    log = tmp_path / "model-runtimes/setup.log"
    assert 0 < log.stat().st_size <= 65536
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_installer_diagnostics_never_write_through_a_planted_symlink(tmp_path: Path) -> None:
    (tmp_path / "model-runtimes").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"owned bytes")
    (tmp_path / "model-runtimes/setup.log").symlink_to(outside)
    with pytest.raises(ModelSetupError):
        RuntimeInstaller(tmp_path).run(
            [sys.executable, "-c", "import sys; print('owned diagnostic'); sys.exit(1)"],
            {},
            threading.Event(),
        )
    log = tmp_path / "model-runtimes/setup.log"
    assert outside.read_bytes() == b"owned bytes"
    assert not log.is_symlink()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_kokoro_language_resources_fit_native_path_limit_in_long_mac_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from aitts import model_worker  # noqa: PLC0415

    root = tmp_path / ("long-application-support-path-" * 3)
    package = root / "venv/lib/python3.12/site-packages/espeakng_loader"
    data = package / "espeak-ng-data"
    data.mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _: SimpleNamespace(origin=str(package / "__init__.py")),
    )
    monkeypatch.setenv("ESPEAK_DATA_PATH", "owned-before-setup")
    model = model_worker.local_engine("kokoro-mlx", root)
    assert model.name == "kokoro-mlx"
    value = os.environ["ESPEAK_DATA_PATH"]
    assert len(value.encode()) < 100
    assert Path(value).resolve() == data


@pytest.mark.parametrize("name", ["chatterbox", "kokoro-mlx"])
def test_missing_saved_model_keeps_daemon_reachable_for_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.delenv("AI_TTS_CHATTERBOX_MODEL_DIR", raising=False)
    store = Store(tmp_path / "state.db")
    try:
        store.set_setting("engine", name)
    finally:
        store.close()
    selected, engines = configured_engines(tmp_path, probe_mlx=lambda: False)
    assert selected.name == "kokoro"
    assert name not in engines
