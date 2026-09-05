# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application policy for bounded audio-cache retention."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CACHE_MAX_BYTES = 1024**3


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One unique audio artifact observed through the cache port."""

    path: Path
    size_bytes: int
    last_access_ns: int


@dataclass(frozen=True, slots=True)
class CacheEnforcementReport:
    """Observable result of enforcing one cache-size limit."""

    before_bytes: int
    after_bytes: int
    max_bytes: int
    evicted_paths: tuple[Path, ...]
    failed_paths: tuple[Path, ...]

    @property
    def within_limit(self) -> bool:
        """Whether the cache reached the requested limit."""
        return self.after_bytes <= self.max_bytes


@dataclass(frozen=True, slots=True)
class CachePurgeReport:
    """Point-in-time result of explicitly purging reusable cached audio."""

    removed_entries: tuple[CacheEntry, ...]
    protected_entries: tuple[CacheEntry, ...]
    failed_entries: tuple[CacheEntry, ...]

    @property
    def removed_bytes(self) -> int:
        """Bytes represented by entries successfully released from the cache."""
        return sum(entry.size_bytes for entry in self.removed_entries)

    @property
    def protected_bytes(self) -> int:
        """Bytes retained because nonterminal speech still owns them."""
        return sum(entry.size_bytes for entry in self.protected_entries)

    @property
    def failed_bytes(self) -> int:
        """Bytes represented by entries whose removal failed."""
        return sum(entry.size_bytes for entry in self.failed_entries)


class AudioCachePort(Protocol):
    """Filesystem-independent audio-cache operations used by the application."""

    def inventory(self) -> tuple[CacheEntry, ...]:
        """Return each unique cached audio artifact exactly once."""
        ...

    def delete(self, path: Path) -> bool:
        """Delete one artifact, returning whether it existed."""
        ...

    def touch(self, path: Path) -> bool:
        """Mark one existing artifact as recently used."""
        ...


class CacheMetadataPort(Protocol):
    """State-store operations required by cache policy."""

    def protected_audio_paths(self) -> frozenset[str]:
        """Return audio paths still referenced by nonterminal work."""
        ...

    def forget_terminal_audio(self, path: Path) -> int:
        """Clear terminal history references to an absent cache artifact."""
        ...


class CacheController:
    """Enforce the LRU cap without evicting audio owed to the listener."""

    def __init__(self, metadata: CacheMetadataPort, cache: AudioCachePort) -> None:
        """Bind durable metadata and an audio-cache adapter."""
        self._metadata = metadata
        self._cache = cache

    def enforce(self, *, max_bytes: int) -> CacheEnforcementReport:
        """Evict least-recent terminal audio until at or below ``max_bytes``."""
        if max_bytes < 0:
            msg = "max_bytes must be non-negative"
            raise ValueError(msg)

        before = self._cache.inventory()
        before_bytes = sum(entry.size_bytes for entry in before)
        remaining_bytes = before_bytes
        protected = self._metadata.protected_audio_paths()
        candidates = sorted(
            (entry for entry in before if str(entry.path) not in protected),
            key=lambda entry: (entry.last_access_ns, str(entry.path)),
        )
        evicted: list[Path] = []
        failed: list[Path] = []
        for entry in candidates:
            if remaining_bytes <= max_bytes:
                break
            try:
                existed = self._cache.delete(entry.path)
            except OSError:
                log.warning("event=cache_eviction_failed")
                failed.append(entry.path)
                continue
            self._metadata.forget_terminal_audio(entry.path)
            if existed:
                evicted.append(entry.path)
                remaining_bytes -= entry.size_bytes

        after_bytes = sum(entry.size_bytes for entry in self._cache.inventory())
        return CacheEnforcementReport(
            before_bytes=before_bytes,
            after_bytes=after_bytes,
            max_bytes=max_bytes,
            evicted_paths=tuple(evicted),
            failed_paths=tuple(failed),
        )

    def purge(self) -> CachePurgeReport:
        """Remove all cached audio not owned by current or pending speech."""
        entries = self._cache.inventory()
        protected_paths = self._metadata.protected_audio_paths()
        protected = tuple(entry for entry in entries if str(entry.path) in protected_paths)
        removed: list[CacheEntry] = []
        failed: list[CacheEntry] = []
        for entry in entries:
            if str(entry.path) in protected_paths:
                continue
            try:
                existed = self._cache.delete(entry.path)
            except OSError:
                log.warning("event=cache_purge_delete_failed")
                failed.append(entry)
                continue
            self._metadata.forget_terminal_audio(entry.path)
            if existed:
                removed.append(entry)

        return CachePurgeReport(
            removed_entries=tuple(removed),
            protected_entries=protected,
            failed_entries=tuple(failed),
        )

    def note_access(self, path: Path) -> bool:
        """Record successful cache reuse for persistent LRU ordering."""
        try:
            return self._cache.touch(path)
        except OSError:
            log.warning("event=cache_access_refresh_failed")
            return False
