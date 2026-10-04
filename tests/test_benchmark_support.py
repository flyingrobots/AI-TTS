# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A selected benchmark source must supply its own version of playback support."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("issue #68: reference playback helpers come from the selected source"),
]
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("helper_name", ["test_playback.py", "support/playback.py"])
def test_alternate_source_executes_its_own_playback_helpers(
    tmp_path: Path, helper_name: str
) -> None:
    """Delete when source selection retires or stronger origin coverage replaces this test."""
    source = tmp_path / "reference"
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    support = source / "tests"
    support.mkdir()
    for name in ("__init__.py", "conftest.py"):
        shutil.copyfile(ROOT / "tests" / name, support / name)
    (support / "support").mkdir()
    (support / "support" / "__init__.py").write_text('"""Owned support package."""\n')
    shutil.copyfile(
        ROOT / "tests" / "fixtures" / "benchmark_legacy_playback.txt",
        support / helper_name,
    )
    marker = tmp_path / "reference-helper-executed"
    # The witness belongs to the selected source, outside the candidate's import tree.
    with (support / helper_name).open("a") as module:
        module.write(f"\nPath({str(marker)!r}).write_text('selected reference')\n")
    output = tmp_path / "report.json"
    result = subprocess.run(  # noqa: S603 - owned source and fixed benchmark CLI
        [
            sys.executable,
            "-B",
            "-m",
            "scripts.benchmarks.run",
            "--source-root",
            str(source),
            "--output",
            str(output),
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--backlog",
            "0",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.is_file(), "benchmark executed candidate helpers for the selected reference"
    assert marker.read_text() == "selected reference"
    report = json.loads(output.read_text())
    assert report["environment"]["playback_support_sha256"][f"tests/{helper_name}"] == (
        hashlib.sha256((support / helper_name).read_bytes()).hexdigest()
    )
    assert report["cases"]["durability"]["recovery"]["recovery.witnesses"] == 8


def test_preloaded_candidate_test_package_cannot_contaminate_reference(tmp_path: Path) -> None:
    """Oracle: a benchmark with mixed source ownership must refuse to publish a report."""
    source = tmp_path / "reference"
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    support = source / "tests"
    support.mkdir()
    for name in ("__init__.py", "conftest.py"):
        shutil.copyfile(ROOT / "tests" / name, support / name)
    shutil.copyfile(
        ROOT / "tests" / "fixtures" / "benchmark_legacy_playback.txt",
        support / "test_playback.py",
    )
    output = tmp_path / "report.json"
    result = subprocess.run(  # noqa: S603 - owned source and intentionally preloaded package
        [
            sys.executable,
            "-B",
            "-c",
            "import tests; from scripts.benchmarks.run import main; raise SystemExit(main())",
            "--source-root",
            str(source),
            "--output",
            str(output),
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--backlog",
            "0",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "mixed-source benchmark published a misleading report"
    assert "test support was already loaded from another checkout" in result.stderr
    assert not output.exists()
