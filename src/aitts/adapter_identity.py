# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Canonical content identity for copied worker packages, excluding bytecode caches."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def adapter_sha256(package: Path) -> str:
    """Hash sorted UTF-8 relative names and bytes, each framed by an unsigned 8-byte length."""
    digest = hashlib.sha256(b"aitts-adapter-v1\0")
    files = sorted(
        (
            path
            for path in package.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.relative_to(package).parts
            and path.suffix != ".pyc"
        ),
        key=lambda path: path.relative_to(package).as_posix().encode("utf-8"),
    )
    for path in files:
        name = path.relative_to(package).as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                digest.update(chunk)
    return digest.hexdigest()
