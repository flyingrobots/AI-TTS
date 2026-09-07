# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Atomic synthesis-artifact publication at the filesystem adapter boundary."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.application.cache import CacheController
from aitts.engine import FakeEngine
from aitts.engines.kokoro import KokoroAssets, KokoroEngine
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


class OneShotPublishFailureArtifacts(FileAudioArtifacts):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._fail_next_publish = True

    def publish(self, utterance_id: str, candidate: Path) -> Path:
        if self._fail_next_publish:
            self._fail_next_publish = False
            msg = "seeded atomic rename failure"
            raise OSError(msg)
        return super().publish(utterance_id, candidate)


class StubKokoroEngine(KokoroEngine):
    """The real encoder path, with the pipeline and the model host stubbed.

    Both have to be stubbed. ``synthesize`` resolves the voice pack to a file
    path — the fix that stopped the engine re-resolving each pack through the
    model host on every load — so an engine given real assets reaches for
    ``huggingface_hub``, which is not a declared dependency and is absent
    wherever the kokoro extra is not installed. This test is about the WAV
    the encoder writes, so neither the network nor that extra belongs in it.
    """

    def __init__(self, *, root: Path) -> None:
        def resolve(*, repo_id: str, filename: str, local_files_only: bool) -> str:
            del repo_id, local_files_only
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"voice pack")
            return str(path)

        super().__init__(assets=KokoroAssets(download=resolve))

    def _pipeline(self, voice: str) -> Any:
        del voice

        def pipeline(
            text: str, *, voice: str, speed: float
        ) -> tuple[tuple[None, None, list[float]]]:
            del text, voice, speed
            return ((None, None, [0.0, 0.0]),)

        return pipeline


@pytest.mark.oracle("KokoroEngine's public synthesize contract promises a WAV artifact")
def test_kokoro_writes_wav_to_atomic_candidate(cache_dir: Path) -> None:
    import soundfile as sf  # noqa: PLC0415 - exercise Kokoro's lazy encoder dependency

    artifacts = FileAudioArtifacts(cache_dir)
    artifacts.prepare()
    candidate = artifacts.target("format-selection")

    engine = StubKokoroEngine(root=cache_dir / "assets")
    duration_ms = engine.synthesize("format", "af_aoede", 1.0, candidate)
    published = artifacts.publish("format-selection", candidate)

    assert {
        "duration_ms": duration_ms,
        "published_name": published.name,
        "published_format": sf.info(str(published)).format,
    } == {
        "duration_ms": 0,
        "published_name": "format-selection.wav",
        "published_format": "WAV",
    }


async def test_inflight_candidate_is_hidden_from_cache_and_explicit_purge(
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
    purge = CacheController(store, cache).purge()
    candidate_during_purge = tuple(path.read_bytes() for path in cache_dir.glob("*.part"))
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
        "purge_removed": purge.removed_entries,
        "candidate_during_purge": candidate_during_purge,
        "published_cache": published,
        "ready_path": None if current is None else Path(current.audio_path or "").name,
        "staging_after_publish": staging,
    } == {
        "engine_started": True,
        "inflight_cache": (),
        "purge_removed": (),
        "candidate_during_purge": (b"partial",),
        "published_cache": (f"{utterance.id}.wav",),
        "ready_path": f"{utterance.id}.wav",
        "staging_after_publish": (),
    }


async def test_publish_failure_is_attached_to_item_and_queue_continues(
    store: Store,
    cache_dir: Path,
) -> None:
    artifacts = OneShotPublishFailureArtifacts(cache_dir)
    pool = SynthesisPool(store, FakeEngine(voices=["v"]), artifacts, workers=1)
    failed = store.submit("publish fails", voice="v", speed=1.0)
    good = store.submit("publish works", voice="v", speed=1.0)
    task = asyncio.create_task(pool.run())
    await wait_for(
        lambda: (current := store.get(good.id)) is not None and current.state is State.READY
    )
    failed_after = store.get(failed.id)
    good_after = store.get(good.id)
    pool_running = not task.done()
    task.cancel()

    assert {
        "failed_state": None if failed_after is None else failed_after.state,
        "failed_error": None if failed_after is None else failed_after.error,
        "good_state": None if good_after is None else good_after.state,
        "pool_running": pool_running,
    } == {
        "failed_state": State.FAILED,
        "failed_error": "artifact publication failed: seeded atomic rename failure",
        "good_state": State.READY,
        "pool_running": True,
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
