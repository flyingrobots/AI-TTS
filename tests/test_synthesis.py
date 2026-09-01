# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Synthesis pool: parallel, failure-isolated, cancellation-aware (architecture §2, §4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aitts.engine import FakeEngine
from aitts.model import State
from aitts.store import Store
from aitts.synthesis import SynthesisPool
from tests.conftest import wait_for


def in_state(store: Store, utt_id: str, state: State) -> object:
    def check() -> bool:
        got = store.get(utt_id)
        return got is not None and got.state is state

    return check


async def run_pool(pool: SynthesisPool) -> asyncio.Task[None]:
    task = asyncio.create_task(pool.run())
    await asyncio.sleep(0)
    return task


async def test_synthesizes_queued_to_ready(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"], duration_ms=1234)
    pool = SynthesisPool(store, engine, cache_dir, workers=1)
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
    pool = SynthesisPool(store, engine, cache_dir, workers=1)
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
    pool = SynthesisPool(store, engine, cache_dir, workers=1)
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
    pool = SynthesisPool(store, engine, cache_dir, workers=2)
    a = store.submit("a", voice="v", speed=1.0)
    b = store.submit("b", voice="v", speed=1.0)
    task = await run_pool(pool)
    await wait_for(in_state(store, a.id, State.READY))
    await wait_for(in_state(store, b.id, State.READY))
    assert engine.max_concurrent == 2
    task.cancel()


async def test_notify_wakes_idle_pool(store: Store, cache_dir: Path) -> None:
    engine = FakeEngine(voices=["v"])
    pool = SynthesisPool(store, engine, cache_dir, workers=1)
    task = await run_pool(pool)
    await asyncio.sleep(0.02)
    utt = store.submit("later", voice="v", speed=1.0)
    pool.notify()
    await wait_for(in_state(store, utt.id, State.READY))
    task.cancel()
