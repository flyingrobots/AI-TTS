# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Contract checks for invoking the selected exporter from a temporary project."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the CLI invokes caller-selected uv even after changing its child cwd"),
]


@pytest.mark.parametrize("selection", ["argument", "path"])
def test_relative_uv_is_resolved_in_the_callers_directory(tmp_path: Path, selection: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[1] / "scripts/check_runtime_requirements.py"
    checker = scripts / source.name
    shutil.copyfile(source, checker)
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).write_text("# owned export fixture\n")
    manifests = tmp_path / "src/aitts/runtime_requirements"
    manifests.mkdir(parents=True)
    (manifests / "kokoro-supplement.txt").write_text("# owned supplement\n")
    for model in ("kokoro", "kokoro-mlx", "chatterbox"):
        supplement = "\n# owned supplement\n" if model != "chatterbox" else ""
        (manifests / f"{model}.txt").write_text("frozen export\n" + supplement)
    tools = tmp_path / "tools"
    tools.mkdir()
    probe = tmp_path / "exporter-calls.txt"
    exporter = tools / "uv"
    exporter.write_text(
        f"#!{sys.executable}\n"
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[-1]).write_text('frozen export\\n')\n"
        f"with Path({str(probe)!r}).open('a') as log: log.write('exported\\n')\n"
    )
    exporter.chmod(0o700)
    argv = [sys.executable, str(checker)]
    if selection == "argument":
        argv += ["--uv", "./tools/uv"]
    environment = {**os.environ, "PATH": "tools" + os.pathsep + os.defpath}
    result = subprocess.run(  # noqa: S603 - owned interpreter, script and temporary export fixture
        argv, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr
    assert probe.read_text().splitlines() == ["exported", "exported", "exported"]
