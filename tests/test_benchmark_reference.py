# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The paired comparator measures only the exact, unmodified pinned reference source."""

import os
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
    """Run git in an owned scratch repository, isolated from user hooks and signing.

    Inherited GIT_* variables are dropped: a hook's GIT_DIR overrides `-C` and
    would otherwise commit this fixture into the repository running the tests.
    """
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
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
        env=environment,
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


def test_inherited_git_environment_cannot_redirect_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Git hooks export GIT_DIR, which overrides `-C`; a pre-push run must not
    # inspect, or write to, the repository that launched it.
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    decoy_head = reference(decoy)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    target = tmp_path / "target"
    target.mkdir()
    commit = reference(target)
    (target / "src" / "aitts" / "injected.py").write_text("SLOW = True\n")
    assert not reference_is_clean(target, commit)
    assert reference_is_clean(decoy, decoy_head)
    assert git(decoy, "rev-parse", "HEAD") == decoy_head


@pytest.mark.parametrize("ignored", [False, True])
def test_import_shadow_is_rejected_before_comparison_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, ignored: bool
) -> None:
    """Oracle: issue #62; an importable shadow must never reach a benchmark worker."""
    import sys  # noqa: PLC0415 - owned interpreter for the import witness

    from scripts.benchmarks import compare  # noqa: PLC0415 - comparator entrypoint

    reference(tmp_path)
    (tmp_path / "src" / "probe.py").write_text('VALUE = "tracked"\n')
    git(tmp_path, "add", "src")
    git(tmp_path, "commit", "--quiet", "-m", "tracked probe")
    commit = git(tmp_path, "rev-parse", "HEAD")
    if ignored:
        (tmp_path / ".git" / "info" / "exclude").write_text("src/probe/\n")
    shadow = tmp_path / "src" / "probe"
    shadow.mkdir()
    (shadow / "__init__.py").write_text('VALUE = "untracked shadow"\n')
    witness = subprocess.check_output(  # noqa: S603 - owned import fixture
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import probe; print(probe.VALUE)",
            str(tmp_path / "src"),
        ],
        text=True,
    )
    assert witness.strip() == "untracked shadow"
    output = tmp_path / "results"
    monkeypatch.setattr(compare, "REFERENCE_COMMIT", commit)
    monkeypatch.setattr(
        sys, "argv", ["compare", "--baseline-root", str(tmp_path), "--output", str(output)]
    )

    def refuse_start(_seed: int) -> None:
        pytest.fail("comparison started with an import-shadowed reference")

    # The scheduling boundary precedes every worker; no real campaign can escape.
    monkeypatch.setattr("scripts.benchmarks.compare.random.Random", refuse_start)
    with pytest.raises(SystemExit) as stopped:
        compare.main()
    assert stopped.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "name", ["hidden.py", "hidden.PY", "hidden.pyc", "hidden.so", "hidden.pyd"]
)
def test_ignored_importable_source_is_rejected(tmp_path: Path, name: str) -> None:
    """Oracle: issue #62; ignore patterns do not make executable source trustworthy."""
    commit = reference(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text(f"src/aitts/{name}\n")
    (tmp_path / "src" / "aitts" / name).write_bytes(b"untrusted importable source")
    assert not reference_is_clean(tmp_path, commit)


def test_ordinary_bytecode_cache_and_unrelated_scratch_are_allowed(tmp_path: Path) -> None:
    """Oracle: issue #62; normal caches and files outside src do not taint the pin."""
    commit = reference(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("__pycache__/\n")
    cache = tmp_path / "src" / "aitts" / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-312.pyc").write_bytes(b"owned bytecode cache")
    (tmp_path / "notes.txt").write_text("unrelated notes")
    assert reference_is_clean(tmp_path, commit)


def test_ignored_symlink_cannot_introduce_an_external_package(tmp_path: Path) -> None:
    """Oracle: issue #62; an ignored link can expose an unpinned import package."""
    commit = reference(tmp_path)
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "__init__.py").write_text("VALUE = 'external'\n")
    (tmp_path / ".git" / "info" / "exclude").write_text("src/aitts/external\n")
    (tmp_path / "src" / "aitts" / "external").symlink_to(outside, target_is_directory=True)
    assert not reference_is_clean(tmp_path, commit)


def test_ignored_code_under_a_directory_with_a_newline_is_rejected(tmp_path: Path) -> None:
    """Oracle: issue #62; path quoting must not hide importable ignored code."""
    commit = reference(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("*.py\n")
    package = tmp_path / "src" / "odd\npackage"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 'shadow'\n")
    assert not reference_is_clean(tmp_path, commit)


def test_sourceless_module_in_cache_directory_is_not_a_normal_cache(tmp_path: Path) -> None:
    """Oracle: only tagged bytecode caches are exempt, not importable bare .pyc files."""
    commit = reference(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("__pycache__/\n")
    cache = tmp_path / "src" / "aitts" / "__pycache__"
    cache.mkdir()
    (cache / "hidden.pyc").write_bytes(b"untrusted sourceless module")
    assert not reference_is_clean(tmp_path, commit)
