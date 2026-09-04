# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Filesystem adapter for synthesized audio-artifact lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class FileAudioArtifacts:
    """Store one synthesized WAV candidate per utterance in a cache directory."""

    def __init__(self, root: Path) -> None:
        """Manage synthesized artifacts beneath ``root``."""
        self._root = root

    def prepare(self) -> None:
        """Create the artifact directory if needed."""
        self._root.mkdir(parents=True, exist_ok=True)

    def target(self, utterance_id: str) -> Path:
        """Return the canonical WAV path for ``utterance_id``."""
        return self._root / f"{utterance_id}.wav"

    @staticmethod
    def is_usable(path: Path) -> bool:
        """Accept only a regular, non-empty file as synthesized audio."""
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def discard(path: Path) -> bool:
        """Remove an artifact without allowing cleanup failure to escape."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        return True
