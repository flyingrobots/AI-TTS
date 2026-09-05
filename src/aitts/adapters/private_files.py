# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""POSIX filesystem controls for confidential daemon state."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

_NO_FOLLOW = os.O_NOFOLLOW | os.O_CLOEXEC


def ensure_private_directory(path: Path, *, normalize_existing: bool = True) -> None:
    """Create and validate one directory without following its final path component."""
    created = False
    try:
        path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True)
        created = True
    except FileExistsError:
        pass

    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | _NO_FOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):  # pragma: no cover - O_DIRECTORY guards this
            message = f"private directory path is not a directory: {path}"
            raise NotADirectoryError(errno.ENOTDIR, message, path)
        if created or normalize_existing:
            os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
    finally:
        os.close(descriptor)


def ensure_private_file(path: Path) -> None:
    """Create or normalize one regular file through a no-follow descriptor."""
    _secure_file(path, flags=os.O_RDWR | os.O_CREAT)


def create_private_file(path: Path) -> None:
    """Exclusively create one empty owner-only regular file."""
    _secure_file(path, flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL)


def secure_existing_file(path: Path) -> bool:
    """Normalize an existing regular file, returning false when it is absent."""
    try:
        _secure_file(path, flags=os.O_RDONLY)
    except FileNotFoundError:
        return False
    return True


def secure_private_state(home: Path) -> None:
    """Create and migrate the daemon's known confidential filesystem layout."""
    ensure_private_directory(home)
    cache = home / "cache"
    ensure_private_directory(cache)
    database = home / "state.db"
    ensure_private_file(database)
    for suffix in ("-wal", "-shm", "-journal"):
        secure_existing_file(Path(f"{database}{suffix}"))
    for member in cache.iterdir():
        if member.is_symlink() or not member.is_file():
            continue
        secure_existing_file(member)


def _secure_file(path: Path, *, flags: int) -> None:
    descriptor = os.open(path, flags | _NO_FOLLOW, PRIVATE_FILE_MODE)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            message = f"private file path is not a regular file: {path}"
            raise OSError(errno.EINVAL, message, path)
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
    finally:
        os.close(descriptor)
