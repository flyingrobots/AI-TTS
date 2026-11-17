# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Issue #116: the daemon selects local models only as worker processes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from aitts.engine import SynthesisError
from aitts.engines.managed import ManagedEngine
from aitts.engines.selection import configured_engines
from tests.test_model_setup import complete_runtime

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("issue #116: no model runs in the daemon process"),
]

# Model packages and the in-process adapters that import them.
MODEL_MODULES = (
    "kokoro",
    "kokoro_mlx",
    "mlx",
    "chatterbox",
    "torch",
    "torchaudio",
    "transformers",
    "misaki",
    "spacy",
    "en_core_web_sm",
    "aitts.engines.kokoro_mlx",
    "aitts.engines.chatterbox",
)


def test_every_local_engine_is_a_worker_even_with_legacy_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_TTS_CHATTERBOX_MODEL_DIR", str(tmp_path / "legacy-snapshot"))
    monkeypatch.delenv("AI_TTS_OPENAI_URL", raising=False)
    root = complete_runtime(tmp_path, "kokoro-mlx")
    selected, engines = configured_engines(tmp_path, override="kokoro-mlx")
    assert set(engines) == {"kokoro", "kokoro-mlx"}
    assert all(isinstance(engine, ManagedEngine) for engine in engines.values())
    assert selected is engines["kokoro-mlx"]
    assert engines["kokoro-mlx"].root == root  # type: ignore[attr-defined]


def test_uninstalled_default_refuses_with_its_setup_command_and_spawns_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_TTS_CHATTERBOX_MODEL_DIR", raising=False)
    monkeypatch.delenv("AI_TTS_OPENAI_URL", raising=False)
    selected, engines = configured_engines(tmp_path)
    assert set(engines) == {"kokoro"}
    assert isinstance(selected, ManagedEngine)
    with pytest.raises(SynthesisError, match="ai-tts model-setup kokoro"):
        selected.warmup()
    assert selected._process is None


def test_daemon_startup_imports_no_model_package(tmp_path: Path) -> None:
    complete_runtime(tmp_path, "chatterbox")
    script = """
import json, sys
from pathlib import Path
from aitts.daemon import Daemon
from aitts.engines.selection import configured_engines
from aitts.playback import FakeSink
from aitts.application.input_activity import NullInputActivity
home = Path(sys.argv[1])
engine, engines = configured_engines(home, override="chatterbox")
daemon = Daemon(home=home, engine=engine, engines=engines, sink=FakeSink(),
                input_activity=NullInputActivity())
daemon._model_setup_catalog()
print(json.dumps(sorted(sys.modules)))
"""
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    result = subprocess.run(  # noqa: S603 - owned interpreter and fixed script
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
        timeout=60,
    )
    loaded = set(json.loads(result.stdout.splitlines()[-1]))
    assert sorted(loaded & set(MODEL_MODULES)) == []
