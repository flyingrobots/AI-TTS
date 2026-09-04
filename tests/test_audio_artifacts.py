# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Atomic synthesis-artifact publication at the filesystem adapter boundary."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.store import Store
from aitts.synthesis import SynthesisPool
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "architecture sections 3 and 6: only completely published audio is cache-visible"
    ),
]


class BlockingCandidateEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__(voices=["v"])
        self.started = threading.Event()
        self.release = threading.Event()

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        del text, voice, speed
        out_path.write_bytes(b"partial")
        self.started.set()
        if not self.release.wait(timeout=2.0):
            msg = "test did not release candidate write"
            raise TimeoutError(msg)
        out_path.write_bytes(b"complete")
        return 8


async def test_inflight_candidate_is_hidden_until_atomic_publish(
    store: Store,
    cache_dir: Path,
) -> None:
    engine = BlockingCandidateEngine()
    cache = FileAudioCache(cache_dir)
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    utterance = store.submit("atomic", voice="v", speed=1.0)
    task = asyncio.create_task(pool.run())

    started = await asyncio.to_thread(engine.started.wait, 1.0)
    inflight = tuple(entry.path.name for entry in cache.inventory())
    engine.release.set()
    await wait_for(
        lambda: (current := store.get(utterance.id)) is not None and current.state is State.READY
    )
    current = store.get(utterance.id)
    published = tuple(entry.path.name for entry in cache.inventory())
    staging = tuple(path.name for path in cache_dir.glob("*.part"))
    task.cancel()

    assert {
        "engine_started": started,
        "inflight_cache": inflight,
        "published_cache": published,
        "ready_path": None if current is None else Path(current.audio_path or "").name,
        "staging_after_publish": staging,
    } == {
        "engine_started": True,
        "inflight_cache": (),
        "published_cache": (f"{utterance.id}.wav",),
        "ready_path": f"{utterance.id}.wav",
        "staging_after_publish": (),
    }


def test_prepare_discards_stale_candidate_without_touching_published_audio(
    cache_dir: Path,
) -> None:
    artifacts = FileAudioArtifacts(cache_dir)
    artifacts.prepare()
    candidate = artifacts.target("orphan")
    candidate.write_bytes(b"partial")
    published = cache_dir / "published.wav"
    published.write_bytes(b"complete")

    FileAudioArtifacts(cache_dir).prepare()

    assert {
        "candidate_exists": candidate.exists(),
        "published_bytes": published.read_bytes(),
    } == {
        "candidate_exists": False,
        "published_bytes": b"complete",
    }
