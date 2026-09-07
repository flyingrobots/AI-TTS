#!/usr/bin/env python3
# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Refuse a release tag that disagrees with the version in the tree.

Building ``v0.2.0`` from a tree whose ``pyproject.toml`` still says ``0.1.0``
produces artifacts that look official and are mislabelled, and the discrepancy
surfaces while somebody is trying to reproduce a bug. The tag, the packaging
metadata and the version the CLI prints must be the same string.

Run as ``check_release_tag.py v0.1.0``. Exit 0 means the three agree.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
# A release tag names one version and nothing else. The workflow triggers on
# "v*", which also matches things like "vnext"; a release built from that would
# be named after nothing.
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:[.-]?(?:a|b|rc|post|dev)\d+)?)$")


def packaged_version(repository: Path) -> str:
    """Read the canonical version from the packaging metadata."""
    with (repository / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    project = document.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        msg = "pyproject.toml has no string project.version"
        raise TypeError(msg)
    return str(project["version"])


def module_version(repository: Path) -> str:
    """Read the version the CLI prints, without importing the package.

    Read as text on purpose: importing would pull in the whole package and its
    dependencies to answer a question about one string, and this runs before
    anything has been built.
    """
    source = (repository / "src" / "aitts" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'(?m)^__version__ = "(?P<version>[^"]+)"$', source)
    if found is None:
        msg = "src/aitts/__init__.py declares no __version__ string"
        raise TypeError(msg)
    return found.group("version")


def main(argv: list[str]) -> int:
    """Check ``argv[0]`` against the tree; return a process exit status."""
    if len(argv) != 1:
        sys.stderr.write("usage: check_release_tag.py <tag>\n")
        return 2
    tag = argv[0]
    matched = TAG.match(tag)
    if matched is None:
        sys.stderr.write(f"{tag!r} is not a release tag of the form v<major>.<minor>.<patch>\n")
        return 1
    tagged = matched.group("version")
    packaged = packaged_version(REPOSITORY)
    module = module_version(REPOSITORY)
    if tagged != packaged or packaged != module:
        sys.stderr.write(
            f"release tag {tag!r} disagrees with the tree: "
            f"pyproject.toml says {packaged!r} and aitts.__version__ says {module!r}\n"
        )
        return 1
    sys.stdout.write(f"tag {tag} matches version {packaged}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
