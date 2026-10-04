# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Git hooks and pytest must not redirect owned fixtures into the caller's repository."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.medium, pytest.mark.oracle("issue #74: inherited Git context isolation")]
REPOSITORY = Path(__file__).parents[1]


def clean_environment() -> dict[str, str]:
    """Keep owned Git setup outside the test's deliberately injected context."""
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def init_repository(path: Path) -> None:
    """Initialize only the explicitly owned destination."""
    subprocess.run(  # noqa: S603 - owned repository, fixed git command
        ["/usr/bin/git", "init", "--quiet", str(path)], check=True, env=clean_environment()
    )


@pytest.mark.parametrize("hook", ["pre-commit", "pre-push"])
def test_hooks_do_not_pass_repository_context_to_validation(tmp_path: Path, hook: str) -> None:
    """Oracle: hook tools receive no caller-specific repository or index override."""
    project = tmp_path / "project"
    init_repository(project)
    commands = tmp_path / "commands"
    commands.mkdir()
    uv = commands / "uv"
    uv.write_text('#!/bin/sh\nenv >> "$AITTS_HOOK_ENVIRONMENT"\n')
    uv.chmod(0o755)
    recorded = tmp_path / "tool-environment"
    inherited = {
        "GIT_DIR": str(project / ".git"),
        "GIT_WORK_TREE": str(project),
        "GIT_COMMON_DIR": str(project / ".git"),
        "GIT_INDEX_FILE": str(project / ".git" / "alternate-index"),
        "GIT_PREFIX": "",
    }
    result = subprocess.run(  # noqa: S603 - real hook with owned uv and Git repository
        ["/bin/sh", str(REPOSITORY / "scripts" / "hooks" / hook)],
        cwd=project,
        env={
            **clean_environment(),
            **inherited,
            "PATH": f"{commands}:/usr/bin:/bin",
            "AITTS_HOOK_ENVIRONMENT": str(recorded),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    observed = {line.split("=", 1)[0] for line in recorded.read_text().splitlines()}
    assert observed.isdisjoint(inherited), "hook leaked Git repository context to validation"


def test_pytest_git_fixture_cannot_reinitialize_the_inherited_repository(tmp_path: Path) -> None:
    """Oracle: issue #74 incident; an owned git init must leave the decoy unchanged."""
    decoy = tmp_path / "decoy"
    init_repository(decoy)
    original_config = (decoy / ".git" / "config").read_bytes()
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(REPOSITORY / "tests" / "conftest.py", suite / "conftest.py")
    (suite / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    medium: owned process test\n    oracle(authority): contract\n"
    )
    (suite / "test_owned_git.py").write_text(
        """import subprocess
import pytest
pytestmark = [pytest.mark.medium, pytest.mark.oracle('issue #74 owned Git fixture')]
@pytest.fixture
def owned_repository(tmp_path):
    target = tmp_path / 'owned.git'
    target.mkdir()
    subprocess.run(['/usr/bin/git', '-C', str(target), 'init', '--bare', '--quiet'], check=True)
    return target

def test_owned_repository_is_the_only_destination(owned_repository):
    assert (owned_repository / 'HEAD').is_file(), 'git init escaped the owned fixture'
"""
    )
    result = subprocess.run(  # noqa: S603 - isolated pytest with an owned decoy Git context
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(suite)],
        cwd=suite,
        env={**clean_environment(), "GIT_DIR": str(decoy / ".git")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert {
        "fixture_passed": result.returncode == 0,
        "decoy_unchanged": (decoy / ".git" / "config").read_bytes() == original_config,
    } == {"fixture_passed": True, "decoy_unchanged": True}, result.stdout + result.stderr
