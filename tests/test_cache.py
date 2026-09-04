# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Bounded audio-cache behavior at the application/filesystem boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from aitts.adapters.filesystem_cache import FileAudioCache  # type: ignore[import-untyped]
from aitts.application.cache import CacheController  # type: ignore[import-untyped]

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
        accessed_ns=30,
        terminal=False,
    )

    report = CacheController(store, FileAudioCache(cache_dir)).enforce(max_bytes=8)

    assert report.before_bytes == 12
    assert report.after_bytes == 8
    assert report.evicted_paths == (oldest_path,)
    assert not oldest_path.exists()
    assert newer_path.read_bytes() == b"bbbb"
    assert ready_path.read_bytes() == b"cccc"
    oldest = store.get(oldest_id)
    newer = store.get(newer_id)
    ready = store.get(ready_id)
    assert oldest is not None
    assert oldest.state is State.PLAYED
    assert oldest.audio_path is None
    assert newer is not None
    assert newer.audio_path == str(newer_path)
    assert ready is not None
    assert ready.state is State.READY
    assert ready.audio_path == str(ready_path)
