# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Each benchmark report names its measured boundary and fingerprints the code that produced it."""

import hashlib
from pathlib import Path

import pytest
from scripts.benchmarks import mlx, run

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "Report identity: measured boundary named; measured source and imported harness hashed"
    ),
]

ROOT = Path(__file__).resolve().parents[1]


def sha256(name: str) -> str:
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def test_controller_report_fingerprints_the_imported_harness() -> None:
    harness = run.identity(ROOT)["harness_sha256"]
    for name in [
        "scripts/benchmarks/run.py",
        "scripts/benchmarks/cases.py",
        "scripts/benchmarks/failures.py",
        "scripts/benchmarks/pcm.py",
        "scripts/benchmarks/metrics.py",
        "scripts/benchmarks/support.py",
    ]:
        assert harness[name] == sha256(name)


def test_mlx_report_names_and_fingerprints_the_adapter_boundary() -> None:
    environment = mlx.provenance(ROOT)
    assert "KokoroMlxEngine" in environment["boundary"]
    assert "PlaybackController" not in environment["boundary"]
    assert environment["source_sha256"]["src/aitts/engines/kokoro_mlx.py"] == sha256(
        "src/aitts/engines/kokoro_mlx.py"
    )
    assert environment["harness_sha256"]["scripts/benchmarks/mlx.py"] == sha256(
        "scripts/benchmarks/mlx.py"
    )


def test_controller_report_fingerprints_source_playback_support() -> None:
    support = run.identity(ROOT)["playback_support_sha256"]
    assert support == {
        name: sha256(name)
        for name in ["tests/__init__.py", "tests/support/__init__.py", "tests/support/playback.py"]
    }
