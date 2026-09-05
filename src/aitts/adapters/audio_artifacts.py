# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Filesystem adapter for synthesized audio-artifact lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aitts.adapters.private_files import (
    create_private_file,
    ensure_private_directory,
    secure_existing_file,
)

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)


class FileAudioArtifacts:
    """Store one synthesized WAV candidate per utterance in a cache directory."""

    def __init__(self, root: Path) -> None:
        """Manage synthesized artifacts beneath ``root``."""
        self._root = root

    def prepare(self) -> None:
        """Create the artifact directory and sweep unpublished crash debris."""
        ensure_private_directory(self._root)
        for member in self._root.iterdir():
            if self._is_candidate(member):
                if not self.discard(member):
                    log.warning("event=stale_synthesis_candidate_discard_failed")
                continue
            if member.is_symlink() or not member.is_file():
                continue
            secure_existing_file(member)

    def target(self, utterance_id: str) -> Path:
        """Return a cache-invisible candidate path for ``utterance_id``."""
        candidate = self._candidate_path(utterance_id)
        if not self.discard(candidate):
            msg = f"could not prepare synthesis candidate {candidate}"
            raise OSError(msg)
        create_private_file(candidate)
        return candidate

    @staticmethod
    def is_usable(path: Path) -> bool:
        """Accept only a regular, non-empty file as synthesized audio."""
        try:
            return not path.is_symlink() and path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def publish(self, utterance_id: str, candidate: Path) -> Path:
        """Atomically replace the canonical WAV with one complete candidate."""
        expected = self._candidate_path(utterance_id)
        if candidate != expected:
            msg = f"unexpected synthesis candidate {candidate}"
            raise ValueError(msg)
        secure_existing_file(candidate)
        published = self._published_path(utterance_id)
        candidate.replace(published)
        return published

    @staticmethod
    def discard(path: Path) -> bool:
        """Remove an artifact without allowing cleanup failure to escape."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    def _candidate_path(self, utterance_id: str) -> Path:
        candidate = self._root / f".{utterance_id}.wav.part"
        if candidate.parent != self._root:
            msg = "utterance id must not contain a path separator"
            raise ValueError(msg)
        return candidate

    def _published_path(self, utterance_id: str) -> Path:
        published = self._root / f"{utterance_id}.wav"
        if published.parent != self._root:
            msg = "utterance id must not contain a path separator"
            raise ValueError(msg)
        return published

    @staticmethod
    def _is_candidate(path: Path) -> bool:
        return path.name.startswith(".") and path.name.endswith(".wav.part")
