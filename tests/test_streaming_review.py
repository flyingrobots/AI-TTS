# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Streaming output follows routes and publishes truthful per-clip evidence."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aitts.adapters.clip_evidence import ClipEvidence
from aitts.application.audio_device import FakeAudioDevice
from aitts.playback import FakeSink, PlaybackController, SoundDeviceSink
from aitts.store import Store
from aitts.streaming import SpoolingPCMStream, StreamingRegistry
from tests.conftest import wait_for
from tests.support.playback import DeterministicPlaybackSchedule
from tests.test_playback import DelayedReleaseSink, start
from tests.test_streaming_pipeline import ManualCallbackDevice

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "published-path handoff, adopted default-device identity and per-stream underflow evidence"
    ),
]


class ControlledReleaseSink(DelayedReleaseSink):
    delayed = True

    def start_stream(
        self, source: SpoolingPCMStream, *, artifact_id: str, position_ms: int = 0
    ) -> None:
        del source
        self.start(Path(artifact_id), position_ms=position_ms)

    def stop(self) -> None:
        if self.delayed:
            super().stop()
        else:
            FakeSink.stop(self)


async def test_rewind_uses_published_path_when_generation_finishes_during_release(
    tmp_path: Path,
) -> None:
    # Retire only with an equivalent controlled publication/transport schedule.
    store = Store(tmp_path / "state.db")
    clip = store.submit("source", voice="v", speed=1)
    work = store.claim_for_synthesis()
    assert work is not None
    candidate = tmp_path / "candidate.part"
    published = tmp_path / f"{work.id}.wav"
    source = SpoolingPCMStream(candidate)
    source.append(b"\x00\x20" * 480)
    streams = StreamingRegistry()
    streams.add(work.id, source)
    store.start_streaming(work)
    sink = ControlledReleaseSink()
    schedule = DeterministicPlaybackSchedule()
    controller = PlaybackController(store, sink, schedule, streams=streams)
    task = await start(controller, schedule)
    rewind = asyncio.create_task(controller.restart_current())
    try:
        await asyncio.wait_for(sink.stop_requested.wait(), timeout=1)
        source.seal()
        candidate.rename(published)
        store.finish_synthesis(work, audio_path=str(published), duration_ms=20)
        streams.finish(work.id)
        sink.release_stop()
        await asyncio.wait_for(rewind, timeout=1)
        assert controller.current_id == clip.id
        assert (sink.started[-1], sink.start_positions[-1]) == (published, 0)
    finally:
        sink.delayed = False
        sink.release_stop()
        await asyncio.gather(rewind, return_exceptions=True)
        await controller.shutdown()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        streams.close()
        store.close()


async def test_streaming_underflow_evidence_starts_fresh_for_each_clip(tmp_path: Path) -> None:
    # Retire with a stronger per-hearing output-evidence contract.
    callback = ManualCallbackDevice()
    evidence = ClipEvidence(tmp_path / "evidence")
    sink = SoundDeviceSink(
        device=FakeAudioDevice(), open_callback_stream=callback.open, evidence=evidence
    )
    counts = []
    for index in range(2):
        identity = f"clip_{index}"
        source = SpoolingPCMStream(tmp_path / f"{identity}.wav")
        source.append(b"\x00\x20" * 240)
        source.seal()
        source.finish()
        callback.opened.clear()
        try:
            sink.start_stream(source, artifact_id=identity)
            assert await asyncio.to_thread(callback.opened.wait, 1)
            output = np.empty((240, 1), dtype=np.float32)
            running = callback.render(output, 240, index == 0)
            if not running:
                callback.finished()
            await asyncio.wait_for(sink.wait(), timeout=1)
            rows = [
                json.loads(line)
                for line in (evidence.root / identity / "playback.jsonl").read_text().splitlines()
            ]
            counts.append(
                [row["output_underflows"] for row in rows if row["event"] == "stream_buffering"]
            )
        finally:
            sink.stop()
            callback.block()
            await asyncio.wait_for(sink.wait(), timeout=1)
            source.release()
    assert counts == [[1], [0]]


class InitiallyUnreadableDevice(FakeAudioDevice):
    def __init__(self) -> None:
        super().__init__()
        self.readings = iter([None, "old-output"])

    def default_output_identity(self) -> str | None:
        return next(self.readings, "new-output")


async def test_streaming_follows_route_after_initial_identity_read_fails(tmp_path: Path) -> None:
    # Scripted identity sequence supplies the ordering; timeout bounds liveness only.
    callback = ManualCallbackDevice()
    openings = []

    @contextlib.contextmanager
    def open_stream(**kwargs: Any) -> Iterator[object]:
        with callback.open(**kwargs) as stream:
            openings.append(stream)
            yield stream

    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    source.append(b"\x00\x20" * 24000)
    sink = SoundDeviceSink(device=InitiallyUnreadableDevice(), open_callback_stream=open_stream)
    try:
        sink.start_stream(source, artifact_id="route-clip")
        assert await asyncio.to_thread(callback.opened.wait, 1)
        await wait_for(lambda: not callback.block()[1], timeout=2)
        await wait_for(lambda: len(openings) == 2)
        assert len(openings) == 2
        assert sink.error is None
    finally:
        sink.stop()
        ended = asyncio.create_task(sink.wait())
        await wait_for(lambda: (callback.block(), ended.done())[1])
        await ended
        source.release()
