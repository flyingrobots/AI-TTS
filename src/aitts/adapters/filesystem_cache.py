# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Local-filesystem adapter for the audio-cache application port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aitts.adapters.private_files import ensure_private_directory, secure_existing_file
from aitts.application.cache import CacheEntry

if TYPE_CHECKING:
    from pathlib import Path


class FileAudioCache:
    """Expose WAV artifacts under one owned directory as an audio cache."""

    def __init__(self, root: Path) -> None:
        """Bind the adapter to ``root`` without touching the filesystem yet."""
        self._root = root

    def inventory(self) -> tuple[CacheEntry, ...]:
        """Inventory regular, non-symlink WAV files directly under the cache root."""
        ensure_private_directory(self._root)
        entries: list[CacheEntry] = []
        for path in sorted(self._root.glob("*.wav")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                secure_existing_file(path)
                stat = path.stat()
            except FileNotFoundError:
                continue
            entries.append(
                CacheEntry(
                    path=path,
                    size_bytes=stat.st_size,
                    last_access_ns=stat.st_mtime_ns,
                )
            )
        return tuple(entries)

    def delete(self, path: Path) -> bool:
        """Delete one regular cache member, never following a path outside the root."""
        member = self._member(path)
        if member is None or member.is_symlink():
            return False
        try:
            member.unlink()
        except FileNotFoundError:
            return False
        return True

    def touch(self, path: Path) -> bool:
        """Refresh one regular cache member's persistent LRU timestamp."""
        member = self._member(path)
        if member is None or member.is_symlink() or not member.is_file():
            return False
        member.touch()
        return True

    def _member(self, path: Path) -> Path | None:
        if path.is_symlink():
            return None
        root = self._root.resolve()
        candidate = path.resolve()
        if candidate.parent != root or candidate.suffix != ".wav":
            return None
        return candidate
