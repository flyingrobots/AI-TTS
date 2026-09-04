# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Synthesis pool: parallel, failure-isolated, cancellation-aware (architecture §2, §4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.store import Store
from aitts.synthesis import SynthesisPool
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "synthesis lifecycle and failure-isolation contracts in architecture sections 2 and 4"
    ),
]


def in_state(store: Store, utt_id: str, state: State) -> object:
    def check() -> bool:
        got = store.get(utt_id)
        return got is not None and got.state is state

    return check


async def run_pool(pool: SynthesisPool) -> asyncio.Task[None]:
    task = asyncio.create_task(pool.run())
    await asyncio.sleep(0)
    return task


class MissingArtifactEngine(FakeEngine):
    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        if text == "missing":
            return 123
        return super().synthesize(text, voice, speed, out_path)


class PartialWriteFailureEngine(FakeEngine):
    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        if text == "partial":
            out_path.write_bytes(b"partial audio")
            msg = "seeded disk full"
            raise OSError(msg)
        return super().synthesize(text, voice, speed, out_path)


async def test_success_without_audio_is_failed_and_queue_continues(
    store: Store, cache_dir: Path
) -> None:
    engine = MissingArtifactEngine(voices=["v"])
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    missing = store.submit("missing", voice="v", speed=1.0)
    good = store.submit("good", voice="v", speed=1.0)
    task = await run_pool(pool)
    await wait_for(in_state(store, good.id, State.READY))
    missing_after = store.get(missing.id)
    good_after = store.get(good.id)
    task.cancel()

    assert {
        "missing_state": None if missing_after is None else missing_after.state,
        "missing_error": None if missing_after is None else missing_after.error,
        "good_state": None if good_after is None else good_after.state,
    } == {
        "missing_state": State.FAILED,
        "missing_error": "synthesis produced no usable audio artifact",
        "good_state": State.READY,
    }


async def test_cleanup_failure_does_not_cancel_synthesis_pool(
    store: Store, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = PartialWriteFailureEngine(voices=["v"])
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    partial = store.submit("partial", voice="v", speed=1.0)
    good = store.submit("good", voice="v", speed=1.0)
    original_unlink = Path.unlink

    def fail_partial_cleanup(
        path: Path,
        missing_ok: bool = False,  # noqa: FBT001, FBT002 - matches Path.unlink
    ) -> None:
        if path.name == f"{partial.id}.wav":
            msg = "seeded cleanup failure"
            raise OSError(msg)
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_partial_cleanup)
    task = await run_pool(pool)

    def good_finished_or_pool_stopped() -> bool:
        good_after = store.get(good.id)
        return task.done() or (good_after is not None and good_after.state is State.READY)

    await wait_for(good_finished_or_pool_stopped)
    partial_after = store.get(partial.id)
    good_after = store.get(good.id)
    pool_running = not task.done()
    if task.done():
        task.exception()
    else:
        task.cancel()

    assert {
        "partial_state": None if partial_after is None else partial_after.state,
        "partial_error": None if partial_after is None else partial_after.error,
        "good_state": None if good_after is None else good_after.state,
        "pool_running": pool_running,
    } == {
        "partial_state": State.FAILED,
        "partial_error": "seeded disk full",
        "good_state": State.READY,
        "pool_running": True,
    }


async def test_synthesizes_queued_to_ready(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"], duration_ms=1234)
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    utt = store.submit("hello", voice="v", speed=1.0)
    task = await run_pool(pool)
    await wait_for(in_state(store, utt.id, State.READY))
    got = store.get(utt.id)
    assert got is not None
    assert got.duration_ms == 1234
    assert got.audio_path is not None
    assert Path(got.audio_path).exists()
    task.cancel()


async def test_failure_is_recorded_and_queue_continues(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"], fail_texts={"bad"})
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    bad = store.submit("bad", voice="v", speed=1.0)
    good = store.submit("good", voice="v", speed=1.0)
    task = await run_pool(pool)
    await wait_for(in_state(store, good.id, State.READY))
    got_bad = store.get(bad.id)
    assert got_bad is not None
    assert got_bad.state is State.FAILED
    assert got_bad.error is not None
    task.cancel()


async def test_cancel_during_synthesis_discards_result(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"], delay_s=0.1)
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    utt = store.submit("slow", voice="v", speed=1.0)
    task = await run_pool(pool)
    await wait_for(in_state(store, utt.id, State.SYNTHESIZING))
    store.transition(utt.id, State.CANCELLED)
    await wait_for(lambda: engine.finished >= 1)
    await asyncio.sleep(0.02)
    got = store.get(utt.id)
    assert got is not None
    assert got.state is State.CANCELLED
    assert got.audio_path is None
    assert list(cache_dir.iterdir()) == []
    task.cancel()


async def test_workers_run_in_parallel(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"], delay_s=0.1)
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=2)
    a = store.submit("a", voice="v", speed=1.0)
    b = store.submit("b", voice="v", speed=1.0)
    task = await run_pool(pool)
    await wait_for(in_state(store, a.id, State.READY))
    await wait_for(in_state(store, b.id, State.READY))
    assert engine.max_concurrent == 2
    task.cancel()


async def test_notify_wakes_idle_pool(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"])
    pool = SynthesisPool(store, engine, FileAudioArtifacts(cache_dir), workers=1)
    task = await run_pool(pool)
    await asyncio.sleep(0.02)
    utt = store.submit("later", voice="v", speed=1.0)
    pool.notify()
    await wait_for(in_state(store, utt.id, State.READY))
    task.cancel()
