# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Owned streaming schedules across transport and restart boundaries."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.application.audio_device import FakeAudioDevice
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink, SoundDeviceSink
from aitts.store import Store
from aitts.streaming import SpoolingPCMStream
from tests.conftest import wait_for
from tests.test_ipc import rpc
from tests.test_streaming_pipeline import ManualCallbackDevice

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "transport controls preserve live source ownership and hold semantics before publication"
    ),
]


class GatedEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__(voices=["bm_daniel"])
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()

    def stream_synthesize(self, text: str, voice: str, speed: float) -> Iterator[bytes]:
        del text, voice, speed
        try:
            yield b"\x00\x20" * 2400
            self.waiting.set()
            if not self.release.wait(5):
                raise TimeoutError
            yield b"\x00\x30" * 2400
        finally:
            self.returned.set()


class StreamingSink(FakeSink):
    def __init__(self) -> None:
        super().__init__()
        self.opened = asyncio.Event()
        self.sources: list[SpoolingPCMStream] = []
        self.offsets: list[int] = []

    def start_stream(
        self, source: SpoolingPCMStream, *, artifact_id: str, position_ms: int = 0
    ) -> None:
        self.sources.append(source)
        self.offsets.append(position_ms)
        super().start(Path(artifact_id), position_ms=position_ms)
        self.opened.set()


@pytest.fixture
async def live_clip(
    tmp_path: Path,
) -> AsyncIterator[tuple[Daemon, GatedEngine, StreamingSink, str]]:
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-live-"))
    engine = GatedEngine()
    sink = StreamingSink()
    daemon = Daemon(home=tmp_path, engine=engine, sink=sink, socket_path=socket_dir / "s")
    clip = daemon.store.submit("Owned source", voice="bm_daniel", speed=1.0)
    await daemon.start()
    try:
        assert await asyncio.to_thread(engine.waiting.wait, 1)
        await asyncio.wait_for(sink.opened.wait(), timeout=1)
        yield daemon, engine, sink, clip.id
    finally:
        engine.release.set()
        await asyncio.to_thread(engine.returned.wait, 1)
        await daemon.stop()
        shutil.rmtree(socket_dir)


async def test_pause_keeps_generation_independent_and_resume_keeps_offset(
    live_clip: tuple[Daemon, GatedEngine, StreamingSink, str],
) -> None:
    daemon, engine, sink, clip_id = live_clip
    sink.advance_to(70)
    await rpc(daemon.socket_path, {"op": "pause"})
    engine.release.set()
    await wait_for(lambda: bool((clip := daemon.store.get(clip_id)) and clip.audio_path))
    paused = daemon.store.get(clip_id)
    assert paused is not None
    assert paused.state is State.PAUSED
    assert paused.duration_ms == 200
    assert bool(sink.paused) is True
    await rpc(daemon.socket_path, {"op": "resume"})
    assert sink.position_ms() == 70
    assert bool(sink.paused) is False
    sink.finish_current()
    await wait_for(lambda: bool((clip := daemon.store.get(clip_id)) and clip.state is State.PLAYED))


async def test_restart_while_generating_reopens_same_source_at_zero(
    live_clip: tuple[Daemon, GatedEngine, StreamingSink, str],
) -> None:
    daemon, engine, sink, _ = live_clip
    sink.advance_to(60)
    result = await rpc(daemon.socket_path, {"op": "rewind"})
    assert result["ok"] is True
    assert sink.offsets == [0, 0]
    assert sink.sources[0] is sink.sources[1]
    assert not engine.release.is_set()


async def test_shutdown_releases_unpublished_stream_without_waiting_for_inference(
    live_clip: tuple[Daemon, GatedEngine, StreamingSink, str],
) -> None:
    daemon, engine, sink, _ = live_clip
    source = sink.sources[0]
    await asyncio.wait_for(daemon.stop(), timeout=1)
    assert not engine.release.is_set()
    with pytest.raises(RuntimeError, match="closed"):
        source.append(b"\x00\x00")
    engine.release.set()
    assert await asyncio.to_thread(engine.returned.wait, 1)


@pytest.mark.parametrize("failure", ["generation", "publication", "metadata"])
async def test_failure_ends_device_in_silence_and_removes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    class FailingEngine(GatedEngine):
        def stream_synthesize(self, text: str, voice: str, speed: float) -> Iterator[bytes]:
            yield from super().stream_synthesize(text, voice, speed)
            if failure == "generation":
                msg = "seeded generation failure"
                raise RuntimeError(msg)

    def refuse_publication(self: FileAudioArtifacts, utterance_id: str, candidate: Path) -> Path:
        del self, utterance_id, candidate
        msg = "seeded publication failure"
        raise OSError(msg)

    if failure == "publication":
        monkeypatch.setattr(FileAudioArtifacts, "publish", refuse_publication)
    if failure == "metadata":

        def refuse_metadata(self: Store, *args: object, **kwargs: object) -> None:
            del self, args, kwargs
            msg = "seeded metadata failure"
            raise OSError(msg)

        monkeypatch.setattr(Store, "finish_synthesis", refuse_metadata)
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-fail-"))
    engine = FailingEngine()
    device = ManualCallbackDevice()
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    daemon = Daemon(home=tmp_path, engine=engine, sink=sink, socket_path=socket_dir / "s")
    clip = daemon.store.submit("Controlled failure", voice="bm_daniel", speed=1.0)
    await daemon.start()
    try:
        assert await asyncio.to_thread(device.opened.wait, 1)
        # Hardware is prepared before synthesis; idle callbacks are silent.
        await wait_for(lambda: bool(device.block()[0][-1, 0] > 0))
        engine.release.set()
        await wait_for(
            lambda: bool((item := daemon.store.get(clip.id)) and item.state is State.FAILED)
        )
        final, running = device.block()
        assert running is True  # physical output stays prepared for the next clip
        assert final[-1, 0] == 0
        assert await asyncio.wait_for(sink.wait(), timeout=1) is False
        assert not list((tmp_path / "cache").rglob("*.part"))
        failed = daemon.store.get(clip.id)
        assert failed is not None
        assert failed.audio_path is None
        assert "seeded" in (failed.error or "")
    finally:
        engine.release.set()
        sink.stop()
        if device.opened.is_set():
            device.block()
        await daemon.stop()
        shutil.rmtree(socket_dir)


async def test_nested_live_preemption_resumes_exact_offsets_without_published_files(
    store: Store, tmp_path: Path
) -> None:
    import contextlib  # noqa: PLC0415

    from aitts.model import Priority  # noqa: PLC0415
    from aitts.playback import PlaybackController  # noqa: PLC0415
    from aitts.streaming import StreamingRegistry  # noqa: PLC0415
    from tests.test_playback import DeterministicPlaybackSchedule, settle, start  # noqa: PLC0415

    registry = StreamingRegistry()
    sink = StreamingSink()
    schedule = DeterministicPlaybackSchedule()
    controller = PlaybackController(store, sink, schedule=schedule, streams=registry)

    def admit(text: str, priority: Priority) -> str:
        clip = store.submit(text, voice="v", speed=1, priority=priority, at_head=True)
        work = store.claim_for_synthesis()
        assert work is not None
        source = SpoolingPCMStream(tmp_path / f"{clip.id}.wav")
        source.append(b"\x00\x20" * 2400)
        registry.add(clip.id, source)
        store.start_streaming(work)
        return clip.id

    base = admit("Base", Priority.NORMAL)
    task = await start(controller, schedule)
    try:
        sink.advance_to(60)
        alert = admit("Alert", Priority.PREEMPT)
        await settle(controller, schedule)
        assert controller.current_id == alert
        sink.advance_to(30)
        nested = admit("Nested", Priority.PREEMPT)
        await settle(controller, schedule)
        assert controller.current_id == nested
        await controller.skip()
        await settle(controller, schedule)
        assert (controller.current_id, sink.offsets[-1]) == (alert, 30)
        await controller.skip()
        await settle(controller, schedule)
        assert (controller.current_id, sink.offsets[-1]) == (base, 60)
        assert sink.overlaps == 0
        assert len(sink.sources) == 5
    finally:
        await controller.shutdown()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        registry.close()


async def test_native_pause_spools_to_completion_and_resumes_without_advancing_held_time(
    tmp_path: Path,
) -> None:
    device = ManualCallbackDevice()
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    source = SpoolingPCMStream(tmp_path / "paused.wav", capacity_frames=480)
    sink.prepare_output()
    try:
        source.append(b"\x00\x20" * 480)
        sink.start_stream(source, artifact_id="paused")
        await wait_for(lambda: bool(device.block()[0][-1, 0] > 0))
        position = sink.position_ms()
        sink.pause()
        faded, running = device.block()
        assert running is True
        assert faded[-1, 0] == 0
        assert sink.position_ms() == position
        source.append(b"\x00\x30" * 4800)  # held producer can exceed the whole ring
        source.seal()
        source.finish()
        for _ in range(3):
            silent, running = device.block()
            assert running is True
            assert not silent.any()
        assert sink.position_ms() == position
        sink.resume()
        await wait_for(lambda: bool(device.block()[0][-1, 0] > 0))
        assert sink.position_ms() > position
    finally:
        sink.stop()
        ended = asyncio.create_task(sink.wait())
        await wait_for(lambda: (device.block(), ended.done())[1])
        await ended
        sink.close_output()
        source.release()


@pytest.mark.oracle("model readiness remains truthful when only prepared output fails")
async def test_output_preparation_failure_does_not_report_a_failed_model(tmp_path: Path) -> None:
    attempted = threading.Event()

    class UnavailableOutput(StreamingSink):
        def prepare_output(self) -> None:
            attempted.set()
            msg = "controlled output unavailable"
            raise OSError(msg)

    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-output-"))
    daemon = Daemon(
        home=tmp_path,
        engine=GatedEngine(),
        sink=UnavailableOutput(),
        socket_path=socket_dir / "s",
    )
    await daemon.start()
    try:
        assert await asyncio.to_thread(attempted.wait, 1)

        async def prepared() -> str:
            async with asyncio.timeout(1):
                while True:
                    status = await rpc(daemon.socket_path, {"op": "snapshot"})
                    if status["runtime"]["model_state"] != "loading":
                        return str(status["runtime"]["model_state"])
                    await asyncio.sleep(0)

        assert await prepared() == "ready"
    finally:
        await daemon.stop()
        shutil.rmtree(socket_dir)


@pytest.mark.parametrize("composite", [False, True])
def test_stream_publication_retains_generation_identity(tmp_path: Path, *, composite: bool) -> None:
    """The publication contract includes durable provenance, even after audio eviction."""
    # Retire only when a stronger generation-identity publication contract replaces this.
    store = Store(tmp_path / "state.db")
    try:
        clip = store.submit(
            "source", voice="v", speed=1, spoken_segments=("first", "second") if composite else None
        )
        work = store.claim_for_synthesis()
        assert work is not None
        store.start_streaming(work)
        audio = tmp_path / f"{work.id}.wav"
        store.finish_synthesis(work, audio_path=str(audio), duration_ms=10)
        store.transition(clip.id, State.CANCELLED)
        store.forget_terminal_audio(audio)
        item = store.get_segment(clip.id, 0) if composite else store.get(clip.id)
        assert item is not None
        assert (item.audio_path, item.generation_artifact_id) == (None, work.id)
    finally:
        store.close()
