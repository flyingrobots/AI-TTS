# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application port for synthesized audio-artifact lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class AudioArtifactPort(Protocol):
    """Filesystem-independent boundary used by the synthesis lifecycle."""

    def prepare(self) -> None:
        """Prepare the artifact destination before workers start."""
        ...

    def target(self, utterance_id: str) -> Path:
        """Return a private empty unpublished output file for one utterance."""
        ...

    def is_usable(self, path: Path) -> bool:
        """Return whether ``path`` is a non-empty playable candidate."""
        ...

    def publish(self, utterance_id: str, candidate: Path) -> Path:
        """Atomically publish one usable candidate and return its durable path."""
        ...

    def discard(self, path: Path) -> bool:
        """Remove ``path`` if present; return false instead of raising on failure."""
        ...
