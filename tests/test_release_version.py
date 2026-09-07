# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""One version, declared twice, and a tag that has to agree with it.

The packaged version lives in ``pyproject.toml`` and is repeated as
``aitts.__version__``, which is what ``ai-tts --version`` prints and what a
bug report will quote. Nothing made them agree, so the CLI could report a
version the wheel was not built as — a discrepancy that is discovered while
trying to reproduce something, which is the worst moment for it.

A release tag is the third declaration. Building ``v0.2.0`` from a tree whose
version still says ``0.1.0`` produces artifacts that look official and are
mislabelled, so the tag is checked against the tree before anything is built.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from aitts import __version__

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the single packaged version declared in pyproject.toml"),
]

REPOSITORY = Path(__file__).resolve().parents[1]
CHECKER = REPOSITORY / "scripts" / "check_release_tag.py"


def packaged_version() -> str:
    """The canonical version, from the packaging metadata."""
    with (REPOSITORY / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    project = document["project"]
    assert isinstance(project, dict)
    version = project["version"]
    assert isinstance(version, str)
    return version


def test_the_module_version_matches_the_packaging_metadata() -> None:
    # `ai-tts --version` prints the module's copy, and a bug report will quote
    # it. It has to be the version the wheel was actually built as.
    assert __version__ == packaged_version()


def check(tag: str) -> subprocess.CompletedProcess[str]:
    """Run the release-tag checker against the real tree."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(CHECKER), tag],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY,
    )


def test_the_tag_for_this_tree_is_accepted() -> None:
    result = check(f"v{packaged_version()}")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tag", ["v9.9.9", "v0.0.1"])
def test_a_tag_that_disagrees_with_the_tree_is_refused(tag: str) -> None:
    result = check(tag)

    # This is the check's whole purpose: artifacts built from an inconsistent
    # tree look official and are mislabelled.
    assert result.returncode != 0
    assert tag in result.stderr
    assert packaged_version() in result.stderr


@pytest.mark.parametrize("tag", ["0.1.0", "release-0.1.0", "v", "", "v0.1", "vx.y.z"])
def test_a_tag_that_is_not_a_version_is_refused(tag: str) -> None:
    result = check(tag)

    # The workflow only fires on `v*`, but "v*" also matches `vnext`, and a
    # release built from that would be named after nothing.
    assert result.returncode != 0


def test_the_checker_requires_exactly_one_tag() -> None:
    without = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY,
    )

    assert without.returncode != 0
