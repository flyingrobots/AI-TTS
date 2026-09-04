# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Bounded audio-cache behavior at the application/filesystem boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.application.cache import CacheController
from aitts.model import State
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("cache eviction contract in architecture section 6"),
]


def _cached_utterance(
    store: Store,
    cache_dir: Path,
    *,
    text: str,
    accessed_ns: int,
    terminal: bool,
) -> tuple[str, Path]:
    utterance = store.submit(text, voice="v", speed=1.0)
    path = cache_dir / f"{utterance.id}.wav"
    path.write_bytes(text[:1].encode() * 4)
    os.utime(path, ns=(accessed_ns, accessed_ns))
    store.transition(utterance.id, State.SYNTHESIZING)
    store.transition(utterance.id, State.READY, audio_path=str(path), duration_ms=10)
    if terminal:
        store.transition(utterance.id, State.PLAYING)
        store.transition(utterance.id, State.PLAYED, played_ms=10)
    return utterance.id, path


def test_cache_cap_evicts_lru_terminal_audio_without_losing_history(
    store: Store, cache_dir: Path
) -> None:
    """Oracle: architecture section 6's cap, LRU, protection, and durable-history promise."""
    oldest_id, oldest_path = _cached_utterance(
        store,
        cache_dir,
        text="a-oldest",
        accessed_ns=10,
        terminal=True,
    )
    newer_id, newer_path = _cached_utterance(
        store,
        cache_dir,
        text="b-newer",
        accessed_ns=20,
        terminal=True,
    )
    ready_id, ready_path = _cached_utterance(
        store,
        cache_dir,
        text="c-ready",
        accessed_ns=5,
        terminal=False,
    )

    report = CacheController(store, FileAudioCache(cache_dir)).enforce(max_bytes=8)

    oldest = store.get(oldest_id)
    newer = store.get(newer_id)
    ready = store.get(ready_id)
    actual = {
        "report": (
            report.before_bytes,
            report.after_bytes,
            report.max_bytes,
            report.evicted_paths,
            report.failed_paths,
            report.within_limit,
        ),
        "files": {
            "oldest": oldest_path.read_bytes() if oldest_path.exists() else None,
            "newer": newer_path.read_bytes() if newer_path.exists() else None,
            "ready": ready_path.read_bytes() if ready_path.exists() else None,
        },
        "rows": {
            "oldest": None if oldest is None else (oldest.state, oldest.audio_path),
            "newer": None if newer is None else (newer.state, newer.audio_path),
            "ready": None if ready is None else (ready.state, ready.audio_path),
        },
    }
    assert actual == {
        "report": (12, 8, 8, (oldest_path,), (), True),
        "files": {"oldest": None, "newer": b"bbbb", "ready": b"cccc"},
        "rows": {
            "oldest": (State.PLAYED, None),
            "newer": (State.PLAYED, str(newer_path)),
            "ready": (State.READY, str(ready_path)),
        },
    }
