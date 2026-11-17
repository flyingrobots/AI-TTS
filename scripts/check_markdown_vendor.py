# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Verify the pinned Markdown source and reconstruct its upstream subset."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent / "vendor" / "markdown"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 256
SHA256_HEX_LENGTH = 64
_LOG = logging.getLogger(__name__)
_GIT_NAME = "git"


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        message = f"vendor record exceeds file allowance: {path.name}"
        raise ValueError(message)
    return data


def _manifest(name: str) -> dict[str, str]:
    lines = _read_bounded(ROOT / name).decode("ascii").splitlines()
    if len(lines) > MAX_FILES:
        message = "vendor _manifest exceeds entry allowance"
        raise ValueError(message)
    result: dict[str, str] = {}
    for line in lines:
        digest, separator, relative = line.partition("  ")
        path = PurePosixPath(relative)
        if (
            separator != "  "
            or len(digest) != SHA256_HEX_LENGTH
            or any(char not in "0123456789abcdef" for char in digest)
            or not relative
            or path.is_absolute()
            or ".." in path.parts
            or relative in result
        ):
            message = "invalid vendor _manifest entry"
            raise ValueError(message)
        result[relative] = digest
    return result


def _verify(directory: Path, expected: dict[str, str]) -> None:
    for relative, digest in expected.items():
        path = directory / relative
        if path.is_symlink() or hashlib.sha256(_read_bounded(path)).hexdigest() != digest:
            message = f"vendor checksum mismatch: {relative}"
            raise ValueError(message)


def main() -> None:
    """Check the modified files and reverse the patch in an owned temporary copy."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    git_executable = shutil.which(_GIT_NAME)
    if git_executable is None:
        raise FileNotFoundError(_GIT_NAME)
    modified = _manifest("MODIFIED-SHA256SUMS")
    upstream = _manifest("UPSTREAM-SHA256SUMS")
    _verify(ROOT, modified)
    allowed = set(modified) | {"MODIFIED-SHA256SUMS", "PATCH.md"}
    observed = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file()}
    if observed != allowed:
        message = "vendor file inventory differs from the recorded subset"
        raise ValueError(message)
    with tempfile.TemporaryDirectory(prefix="aitts-vendor-check-") as temporary:
        directory = Path(temporary)
        for relative in modified:
            if relative in {"local.patch", "UPSTREAM-SHA256SUMS"}:
                continue
            destination = directory / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(_read_bounded(ROOT / relative))
        subprocess.run(  # noqa: S603 -- fixed Git operation; verified patch, owned temporary directory.
            [git_executable, "apply", "--reverse", str(ROOT / "local.patch")],
            cwd=directory,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            check=True,
            timeout=10,
            capture_output=True,
        )
        _verify(directory, upstream)
        restored = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        }
        if restored != set(upstream):
            message = "reversed local patch did not restore the upstream subset"
            raise ValueError(message)
    _LOG.info("Markdown vendor: %s upstream files reconstructed and verified", len(upstream))


if __name__ == "__main__":
    main()
