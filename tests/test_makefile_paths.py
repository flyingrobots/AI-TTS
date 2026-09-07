# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Configured paths reach the shell as data, not as source (Makefile).

`make` pastes a variable's value into the recipe text before the shell sees
it, so an overridden path containing a space becomes two arguments and one
containing a glob is expanded. For a recipe built around `rm -rf`, that is
the difference between removing one directory and removing two.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the Makefile's documented DIST override, used by `make clean`"),
]

REPO = Path(__file__).parents[1]
MAKE = shutil.which("make") or "/usr/bin/make"


def make(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run make in ``cwd`` against this repository's Makefile."""
    return subprocess.run(  # noqa: S603 - fixed programme, test-controlled args
        [MAKE, "-f", str(REPO / "Makefile"), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "MAKEFLAGS": ""},
        check=False,
    )


def test_clean_removes_one_directory_even_when_its_name_has_a_space(
    tmp_path: Path,
) -> None:
    target = tmp_path / "build output"
    target.mkdir()
    (target / "artifact").write_text("x", encoding="utf-8")
    bystander = tmp_path / "output"
    bystander.mkdir()
    (bystander / "precious").write_text("keep me", encoding="utf-8")

    result = make("clean", "DIST=build output", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert not target.exists()
    # Word-splitting turned one operand into two and deleted a directory the
    # caller never named.
    assert bystander.exists()
    assert (bystander / "precious").read_text(encoding="utf-8") == "keep me"


def test_clean_does_not_expand_a_glob_in_a_configured_path(tmp_path: Path) -> None:
    (tmp_path / "keep-a").mkdir()
    (tmp_path / "keep-b").mkdir()

    result = make("clean", "DIST=keep-*", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "keep-a").exists()
    assert (tmp_path / "keep-b").exists()
