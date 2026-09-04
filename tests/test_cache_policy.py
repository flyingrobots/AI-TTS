# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Generated and fault-injected checks for the pure cache policy."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aitts.application.cache import CacheController, CacheEntry

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("reference model for architecture section 6 cache policy"),
]


class MemoryAudioCache:
    def __init__(self, entries: list[CacheEntry]) -> None:
        self.entries = entries
        self.deleted: list[Path] = []

    def inventory(self) -> tuple[CacheEntry, ...]:
        return tuple(self.entries)

    def delete(self, path: Path) -> bool:
        for index, entry in enumerate(self.entries):
            if entry.path == path:
                self.entries.pop(index)
                self.deleted.append(path)
                return True
        return False

    def touch(self, path: Path) -> bool:
        return any(entry.path == path for entry in self.entries)


class FailingDeleteCache(MemoryAudioCache):
    def delete(self, path: Path) -> bool:
        del path
        msg = "seeded unlink failure"
        raise OSError(msg)


class MemoryMetadata:
    def __init__(self, protected: frozenset[str]) -> None:
        self.protected = protected
        self.forgotten: list[Path] = []

    def protected_audio_paths(self) -> frozenset[str]:
        return self.protected

    def forget_terminal_audio(self, path: Path) -> int:
        self.forgotten.append(path)
        return 1


@settings(max_examples=100, derandomize=True, database=None)
@given(
    rows=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=100),
            st.integers(min_value=0, max_value=100),
            st.booleans(),
        ),
        min_size=1,
        max_size=8,
    ),
    max_bytes=st.integers(min_value=0, max_value=800),
)
def test_generated_eviction_plan_matches_lru_reference_model(
    rows: list[tuple[int, int, bool]], max_bytes: int
) -> None:
    entries = [
        CacheEntry(Path(f"/cache/{index}.wav"), size, accessed)
        for index, (size, accessed, _protected) in enumerate(rows)
    ]
    protected = frozenset(
        str(entries[index].path)
        for index, (_size, _accessed, is_protected) in enumerate(rows)
        if is_protected
    )
    expected_deleted: list[Path] = []
    expected_remaining = sum(entry.size_bytes for entry in entries)
    for entry in sorted(
        (entry for entry in entries if str(entry.path) not in protected),
        key=lambda item: (item.last_access_ns, str(item.path)),
    ):
        if expected_remaining <= max_bytes:
            break
        expected_deleted.append(entry.path)
        expected_remaining -= entry.size_bytes

    cache = MemoryAudioCache(entries.copy())
    metadata = MemoryMetadata(protected)
    report = CacheController(metadata, cache).enforce(max_bytes=max_bytes)

    assert {
        "before": report.before_bytes,
        "after": report.after_bytes,
        "evicted": report.evicted_paths,
        "failed": report.failed_paths,
        "within_limit": report.within_limit,
        "adapter_deleted": tuple(cache.deleted),
        "metadata_forgotten": tuple(metadata.forgotten),
    } == {
        "before": sum(entry.size_bytes for entry in entries),
        "after": expected_remaining,
        "evicted": tuple(expected_deleted),
        "failed": (),
        "within_limit": expected_remaining <= max_bytes,
        "adapter_deleted": tuple(expected_deleted),
        "metadata_forgotten": tuple(expected_deleted),
    }


def test_seeded_unlink_failure_preserves_history_reference_and_reports_debt() -> None:
    path = Path("/cache/terminal.wav")
    cache = FailingDeleteCache([CacheEntry(path, size_bytes=4, last_access_ns=1)])
    metadata = MemoryMetadata(frozenset())

    report = CacheController(metadata, cache).enforce(max_bytes=0)

    assert {
        "after": report.after_bytes,
        "failed": report.failed_paths,
        "within_limit": report.within_limit,
        "forgotten": tuple(metadata.forgotten),
    } == {
        "after": 4,
        "failed": (path,),
        "within_limit": False,
        "forgotten": (),
    }
