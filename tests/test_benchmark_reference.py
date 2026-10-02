# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The paired comparator measures only the exact, unmodified pinned reference source."""

import subprocess
from pathlib import Path

import pytest
from scripts.benchmarks.compare import reference_is_clean

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "Pinned reference checkout: exact commit and no tracked or untracked src edits"
    ),
]

GIT = "/usr/bin/git"


def git(root: Path, *args: str) -> str:
    """Run git in an owned scratch repository, isolated from user hooks and signing."""
    return subprocess.check_output(  # noqa: S603 - fixed binary and owned repository
        [
            GIT,
            "-C",
            str(root),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Benchmark Fixture",
            "-c",
            "user.email=fixture@invalid",
            *args,
        ],
        text=True,
    ).strip()


def reference(root: Path) -> str:
    """Commit a minimal reference tree and return its commit identity."""
    (root / "src" / "aitts").mkdir(parents=True)
    (root / "src" / "aitts" / "__init__.py").write_text('"""Reference."""\n')
    git(root, "init", "--quiet")
    git(root, "add", "src")
    git(root, "commit", "--quiet", "-m", "reference")
    return git(root, "rev-parse", "HEAD")


def test_clean_pinned_reference_is_accepted(tmp_path: Path) -> None:
    assert reference_is_clean(tmp_path, reference(tmp_path))


def test_other_commit_is_rejected(tmp_path: Path) -> None:
    reference(tmp_path)
    assert not reference_is_clean(tmp_path, "0" * 40)


def test_tracked_source_edit_is_rejected(tmp_path: Path) -> None:
    commit = reference(tmp_path)
    (tmp_path / "src" / "aitts" / "__init__.py").write_text('"""Edited."""\n')
    assert not reference_is_clean(tmp_path, commit)


def test_untracked_source_module_is_rejected(tmp_path: Path) -> None:
    commit = reference(tmp_path)
    (tmp_path / "src" / "aitts" / "injected.py").write_text("SLOW = True\n")
    assert not reference_is_clean(tmp_path, commit)
