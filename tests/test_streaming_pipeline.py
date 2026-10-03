# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Streaming PCM source contract; no device, clock sleeps, or inference model."""

import asyncio
import contextlib
import shutil
import struct
import sys
import tempfile
import threading
import types
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aitts.application.audio_device import FakeAudioDevice
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.engines.kokoro import KokoroAssets, KokoroEngine
from aitts.model import State
from aitts.playback import FakeSink, SoundDeviceSink
from aitts.store import Store
from aitts.streaming import CircularAudioBuffer, PCMStreamRenderer, SpoolingPCMStream
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "bounded PCM ordering, nonblocking underflow, source-only progress, complete cached WAV"
    ),
]


def pcm(*samples: int) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_ring_wraps_without_overwriting_unconsumed_frames() -> None:
    ring = CircularAudioBuffer(4)
    assert ring.write(pcm(1, 2, 3)) == 3
    assert ring.read(2) == pcm(1, 2)
    assert ring.write(pcm(4, 5, 6, 7)) == 3
    assert ring.read(9) == pcm(3, 4, 5, 6)
    assert ring.frames == 0


def test_first_frames_are_readable_before_seal_and_underflow_is_not_eof(tmp_path: Path) -> None:
    path = tmp_path / "candidate.wav"
    stream = SpoolingPCMStream(path, capacity_frames=4)
    try:
        stream.append(pcm(100, 200))
        assert stream.wait_buffered(2, timeout=1)
        first = stream.read(2)
        assert first.pcm == pcm(100, 200)
        assert first.position_frames == 2
        assert first.ended is False
        gap = stream.read(4)
        assert gap.pcm == b""
        assert gap.position_frames == 2
        assert gap.ended is False
        stream.append(pcm(300, 400))
        stream.seal()
        assert stream.wait_buffered(2, timeout=1)
        tail = stream.read(4)
        assert tail.pcm == pcm(300, 400)
        assert tail.ended is False  # final PCM is not permission to publish Played
        stream.finish()
        assert stream.read(4).ended is True
        with wave.open(str(path)) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24_000)
            assert wav.readframes(20) == pcm(100, 200, 300, 400)
    finally:
        stream.close()


def test_paused_consumer_does_not_block_spooling_and_can_seek_back(tmp_path: Path) -> None:
    stream = SpoolingPCMStream(tmp_path / "candidate.wav", capacity_frames=3)
    try:
        # Twenty frames exceed the entire ring. Producer must finish without a reader.
        samples = pcm(*range(20))
        stream.append(samples)
        stream.seal()
        stream.finish()
        stream.seek(12)
        assert stream.wait_buffered(3, timeout=1)
        assert stream.read(3).pcm == pcm(12, 13, 14)
        stream.seek(1)
        assert stream.wait_buffered(3, timeout=1)
        block = stream.read(3)
        assert block.pcm == pcm(1, 2, 3)
        assert block.position_frames == 4
    finally:
        stream.close()


async def test_daemon_starts_playback_before_engine_releases_final_frames(tmp_path: Path) -> None:
    class GatedStreamingEngine(FakeEngine):
        def __init__(self) -> None:
            super().__init__(voices=["bm_daniel"])
            self.first_yielded = threading.Event()
            self.release_tail = threading.Event()

        def stream_synthesize(self, text: str, voice: str, speed: float) -> Iterator[bytes]:
            del text, voice, speed
            yield pcm(100, 200)
            self.first_yielded.set()
            if not self.release_tail.wait(3):
                msg = "test did not release the tail"
                raise TimeoutError(msg)
            yield pcm(300, 400)

        def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
            with wave.open(str(out_path), "wb") as wav:
                wav.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
                for block in self.stream_synthesize(text, voice, speed):
                    wav.writeframesraw(block)
            return 1

    class ObservingStreamingSink(FakeSink):
        def __init__(self) -> None:
            super().__init__()
            self.stream_started = asyncio.Event()

        def start_stream(
            self, source: SpoolingPCMStream, *, artifact_id: str, position_ms: int = 0
        ) -> None:
            self.source = source
            super().start(Path(artifact_id), position_ms=position_ms)
            self.stream_started.set()

    socket_home = Path(tempfile.mkdtemp(prefix="aitts-pcm-"))
    engine = GatedStreamingEngine()
    sink = ObservingStreamingSink()
    daemon = Daemon(home=tmp_path, engine=engine, sink=sink, socket_path=socket_home / "s")
    clip = daemon.store.submit("Owned streaming source", voice="bm_daniel", speed=1.0)
    await daemon.start()
    try:
        assert await asyncio.to_thread(engine.first_yielded.wait, 1)
        await asyncio.wait_for(sink.stream_started.wait(), timeout=1)
        assert not engine.release_tail.is_set()
        assert sink.source.wait_buffered(2, timeout=1)
        assert sink.source.read(2).pcm == pcm(100, 200)
        engine.release_tail.set()
        await wait_for(lambda: bool((item := daemon.store.get(clip.id)) and item.audio_path))
        item = daemon.store.get(clip.id)
        assert item is not None
        assert item.audio_path is not None
        cached = Path(item.audio_path)
        with wave.open(str(cached)) as wav:
            assert wav.readframes(10) == pcm(100, 200, 300, 400)
    finally:
        engine.release_tail.set()
        await daemon.stop()
        shutil.rmtree(socket_home)


# Largest sample-to-sample step accepted across an underrun on a steady 0.5
# signal. The 20 ms raised cosine peaks near 0.5 * pi / (2 * 480).
_UNDERRUN_MAX_STEP = 0.01
_REBUFFER = 24000 * 3 // 10  # 300 ms at the stream rate


@pytest.mark.oracle(
    "listener report 2026-10-02: replay under live synthesis crackled; #57/#34 rule that "
    "every mid-clip silence transition uses a 20 ms raised cosine, never a sub-buffer ramp"
)
def test_device_renderer_fades_underrun_without_advancing_source_clock(tmp_path: Path) -> None:
    """Starving output fades the real upcoming audio, rebuffers, then fades back in."""
    stream = SpoolingPCMStream(tmp_path / "candidate.wav", capacity_frames=20_000)
    try:
        renderer = PCMStreamRenderer(stream)
        stream.append(pcm(*([16384] * 1500)))
        assert stream.wait_buffered(1500, timeout=1)
        heard = [renderer.render(1024)]
        before = renderer.position_frames
        # 476 frames remain: less than a block, so this block starves.
        heard.append(renderer.render(1024))
        assert renderer.underruns == 1
        assert renderer.ended is False
        faded_at = renderer.position_frames
        # The fade reads ahead without consuming, so it can be heard again.
        assert faded_at == before
        # A trickle below the rebuffer threshold must not restart playback.
        stream.append(pcm(*([16384] * 400)))
        assert stream.wait_buffered(400, timeout=1)
        heard.append(renderer.render(1024))
        assert not np.any(heard[-1]), "playback restarted before the rebuffer cushion"
        assert renderer.position_frames == faded_at
        stream.append(pcm(*([16384] * _REBUFFER)))
        assert stream.wait_buffered(_REBUFFER, timeout=1)
        heard.append(renderer.render(1024))
        output = np.concatenate(heard)[:, 0]
        steps = np.abs(np.diff(output))
        assert np.max(steps) <= _UNDERRUN_MAX_STEP, "the underrun has an audible step"
        assert heard[-1][0, 0] == 0, "playback resumed at full amplitude"
        assert renderer.position_frames == faded_at + 1024
        assert renderer.underruns == 1
    finally:
        stream.close()


@pytest.mark.oracle(
    "listener report 2026-10-02: 42 underruns in under a second of replayed audio crackled"
)
def test_trickling_synthesis_rebuffers_once_instead_of_crackling(tmp_path: Path) -> None:
    """Arrivals smaller than a block give one clean gap, not a gap per callback."""
    stream = SpoolingPCMStream(tmp_path / "candidate.wav", capacity_frames=40_000)
    try:
        renderer = PCMStreamRenderer(stream)
        stream.append(pcm(*([16384] * 1200)))
        assert stream.wait_buffered(1200, timeout=1)
        blocks = [renderer.render(1024)]
        # Synthesis falls behind: 300 frames arrive per 1024-frame callback.
        for _ in range(30):
            stream.append(pcm(*([16384] * 300)))
            assert stream.wait_buffered(300, timeout=1)
            blocks.append(renderer.render(1024))
        output = np.concatenate(blocks)[:, 0]
        audible = output != 0
        restarts = int(np.count_nonzero(audible[1:] & ~audible[:-1]))
        assert restarts <= 2, f"playback restarted {restarts} times: crackle"
        assert renderer.underruns <= 2
        assert np.max(np.abs(np.diff(output))) <= _UNDERRUN_MAX_STEP
    finally:
        stream.close()


def test_crash_during_audible_generation_recovers_source_held_for_regeneration(
    tmp_path: Path,
) -> None:

    path = tmp_path / "state.db"
    store = Store(path)
    clip = store.submit("Keep this source", voice="bm_daniel", speed=1.0)
    work = store.claim_for_synthesis()
    assert work is not None
    store.start_streaming(work)
    store.transition(clip.id, State.PLAYING)
    store.close()
    recovered = Store(path)
    try:
        recovered.recover()
        item = recovered.get(clip.id)
        assert item is not None
        assert item.text == "Keep this source"
        assert item.state is State.QUEUED
        assert item.audio_path is None
        assert recovered.get_setting("playback_held", "false") == "true"
        regenerated = recovered.claim_for_synthesis()
        assert regenerated is not None
        assert regenerated.utterance_id == clip.id
    finally:
        recovered.close()


class ManualCallbackDevice:
    def __init__(self) -> None:
        self.opened = threading.Event()
        self._callback_lock = threading.Lock()
        self._active = False
        self.render: Callable[[Any, int, bool], bool]
        self.finished: Callable[[], None]

    @contextlib.contextmanager
    def open(
        self,
        *,
        samplerate: int,
        channels: int,
        render: Callable[[Any, int, bool], bool],
        finished: Callable[[], None],
    ) -> Iterator[object]:
        assert (samplerate, channels) == (24_000, 1)
        with self._callback_lock:
            self.render = render
            self.finished = finished
            self._active = True
        self.opened.set()
        try:
            yield object()
        finally:
            with self._callback_lock:
                self._active = False

    @contextlib.contextmanager
    def driving(self) -> Iterator[None]:
        """Supply native callbacks while the caller performs blocking teardown."""
        stopped = threading.Event()

        def drive() -> None:
            while not stopped.is_set():
                if self.opened.is_set():
                    self.block()
                stopped.wait(0.001)

        worker = threading.Thread(target=drive)
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            worker.join(1)

    def block(self) -> tuple[Any, bool]:
        # Manual and background driving share ownership with open/close. An
        # ended stream cannot deliver a late finished callback into a new one.
        with self._callback_lock:
            output = np.zeros((240, 1), dtype=np.float32)
            if not self._active:
                return output, False
            running = self.render(output, 240, False)  # noqa: FBT003 - native callback
            if not running:
                self._active = False
                self.finished()
            return output, running


async def test_sound_device_callback_starts_live_and_drains_only_after_publication(
    tmp_path: Path,
) -> None:

    device = ManualCallbackDevice()
    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    try:
        source.append(pcm(*([8192] * 480)))
        sink.start_stream(source, artifact_id="owned")
        assert await asyncio.to_thread(device.opened.wait, 1)
        assert source.wait_buffered(480, timeout=1)
        first, running = device.block()
        assert running is True
        assert first[-1, 0] == pytest.approx(0.25)
        assert sink.position_ms() == 10
        source.seal()
        _, running = device.block()
        assert running is True
        _, running = device.block()
        assert running is True  # no false EOF while publication is pending
        source.finish()
        final, running = device.block()
        assert running is False
        assert final[-1, 0] == 0
        assert await asyncio.wait_for(sink.wait(), timeout=1) is True
        assert sink.position_ms() == 20
    finally:
        sink.stop()
        if device.opened.is_set():
            device.block()
        source.close()


def test_kokoro_yields_bounded_pcm_before_requesting_next_inference_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    yielded: list[int] = []

    class Model:
        def __init__(self, **_: object) -> None:
            pass

        def eval(self) -> "Model":
            return self

    class Pipeline:
        def __init__(self, **_: object) -> None:
            self.g2p = lambda text: text

        def __call__(self, text: str, **_: object) -> Iterator[Any]:
            del text
            yielded.append(1)
            yield types.SimpleNamespace(audio=np.array([0, 0.5, -0.5, 1, -1] * 1000))
            yielded.append(2)
            yield types.SimpleNamespace(audio=np.zeros(2400))

    upstream = types.ModuleType("kokoro")
    upstream.KModel = Model  # type: ignore[attr-defined]
    upstream.KPipeline = Pipeline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro", upstream)
    engine = KokoroEngine(assets=KokoroAssets(download=lambda **_: str(tmp_path / "owned-model")))
    output = engine.stream_synthesize("Owned source", "af_heart", 1.0)
    first = next(output)
    assert len(first) == 4800
    assert first[:10] == pcm(0, 16384, -16384, 32767, -32768)
    assert yielded == [1]
    frames = [first, *output]
    assert [len(block) for block in frames] == [4800, 4800, 400, 4800]
    assert b"".join(frames) == pcm(*([0, 16384, -16384, 32767, -32768] * 1000), *([0] * 2400))


def test_cached_wav_is_read_only_and_supports_backward_seek(tmp_path: Path) -> None:
    path = tmp_path / "cached.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        writer.writeframes(pcm(*range(600)))
    original = path.read_bytes()
    source = SpoolingPCMStream.from_cached(path)
    try:
        assert source.wait_buffered(600, timeout=1)
        assert source.read(600).pcm == pcm(*range(600))
        assert source.read(1).ended is True
        source.seek(100)
        assert source.wait_buffered(500, timeout=1)
        assert source.read(500).pcm == pcm(*range(100, 600))
        assert source.read(1).ended is True
    finally:
        source.release()
    assert path.read_bytes() == original


@pytest.mark.parametrize("contents", [b"not a wav", b"RIFF"])
def test_invalid_cached_file_refuses_streaming_without_modifying_it(
    tmp_path: Path, contents: bytes
) -> None:
    path = tmp_path / "invalid.wav"
    path.write_bytes(contents)
    with pytest.raises(ValueError, match="not streaming PCM"):
        SpoolingPCMStream.from_cached(path)
    assert path.read_bytes() == contents


def test_restart_recovers_only_unpublished_composite_child(tmp_path: Path) -> None:
    path = tmp_path / "composite.db"
    store = Store(path)
    clip = store.submit("Two parts", voice="v", speed=1, spoken_segments=("First", "Second"))
    first = store.claim_for_synthesis()
    assert first is not None
    store.finish_synthesis(first, audio_path="/owned/first.wav", duration_ms=100)
    store.transition(clip.id, State.PLAYING)
    store.transition_segment(clip.id, 0, State.PLAYING)
    store.transition_segment(clip.id, 0, State.PLAYED)
    second = store.claim_for_synthesis()
    assert second is not None
    store.start_streaming(second)
    store.transition_segment(clip.id, 1, State.PLAYING)
    store.close()
    recovered = Store(path)
    try:
        recovered.recover()
        recovered.recover()  # recovery is idempotent, even with a completed earlier child
        children = recovered.segments(clip.id)
        assert [(child.state, child.audio_path) for child in children] == [
            (State.PLAYED, "/owned/first.wav"),
            (State.QUEUED, None),
        ]
        parent = recovered.get(clip.id)
        assert parent is not None
        assert parent.state is State.PAUSED
        assert recovered.get_setting("playback_held", "false") == "true"
        replacement = recovered.claim_for_synthesis()
        assert replacement is not None
        assert replacement.segment_index == 1
        recovered.start_streaming(replacement)
        recovered.finish_synthesis(replacement, audio_path="/owned/second.wav", duration_ms=200)
        parent = recovered.get(clip.id)
        assert parent is not None
        assert (parent.state, parent.duration_ms) == (State.PAUSED, 300)
    finally:
        recovered.close()


@pytest.mark.parametrize("operation", ["admission", "publication", "recovery"])
def test_failed_streaming_commit_remains_recoverable(tmp_path: Path, operation: str) -> None:
    import sqlite3  # noqa: PLC0415 - seeded durable boundary

    from tests.test_store import OneShotCommitFailure  # noqa: PLC0415

    connections: list[OneShotCommitFailure] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=OneShotCommitFailure)
        connections.append(connection)
        return connection

    path = tmp_path / "fault.db"
    store = Store(path, connect=connect)
    clip = store.submit("Retained source", voice="v", speed=1)
    work = store.claim_for_synthesis()
    assert work is not None
    if operation != "admission":
        store.start_streaming(work)
        store.transition(clip.id, State.PLAYING)
    connections[0].fail_next_commit = True
    with pytest.raises(sqlite3.OperationalError, match="seeded commit failure"):  # noqa: PT012 - select seeded transaction
        if operation == "admission":
            store.start_streaming(work)
        elif operation == "publication":
            store.finish_synthesis(work, audio_path="/owned/uncommitted.wav", duration_ms=100)
        else:
            store.recover()
    visible = store.get(clip.id)
    assert visible is not None
    assert visible.audio_path is None
    assert visible.state is (State.SYNTHESIZING if operation == "admission" else State.PLAYING)
    store.close()
    recovered = Store(path)
    try:
        recovered.recover()
        item = recovered.get(clip.id)
        assert item is not None
        assert (item.text, item.state, item.audio_path) == ("Retained source", State.QUEUED, None)
        if operation != "admission":
            assert recovered.get_setting("playback_held", "false") == "true"
    finally:
        recovered.close()


def test_initial_digital_silence_can_be_skipped_without_changing_cached_audio(
    tmp_path: Path,
) -> None:
    path = tmp_path / "leading-silence.wav"
    source = SpoolingPCMStream(path)
    samples = pcm(*([0] * 4800 + [8192] * 240 + [0] * 240 + [16384] * 240))
    try:
        source.append(samples)
        source.seal()
        source.finish()
        renderer = PCMStreamRenderer(source, skip_leading_silence=True)
        first = renderer.render(240)
        assert first[-1, 0] == pytest.approx(0.25)
        assert renderer.skipped_silence_frames == 4800
        assert renderer.position_frames == 5040
        middle = renderer.render(240)
        assert not middle.any()  # an intentional pause after speech is retained
        assert renderer.position_frames == 5280
        last = renderer.render(240)
        assert last[-1, 0] == pytest.approx(0.5)
        assert renderer.ended is True
        with wave.open(str(path)) as cached:
            assert cached.readframes(6000) == samples
    finally:
        source.close()


def test_leading_silence_skip_waits_for_more_pcm_and_does_not_apply_to_a_seek(
    tmp_path: Path,
) -> None:
    source = SpoolingPCMStream(tmp_path / "incremental.wav")
    try:
        source.append(pcm(*([0] * 240)))
        renderer = PCMStreamRenderer(source, skip_leading_silence=True)
        assert not renderer.render(240).any()
        assert renderer.ended is False
        assert renderer.skipped_silence_frames == 240
        source.append(pcm(*([8192] * 480)))
        source.seal()
        source.finish()
        resumed = renderer.render(240)
        assert resumed[-1, 0] == pytest.approx(0.25)
        assert renderer.position_frames == 480
        sought = PCMStreamRenderer(source, position_frames=1, skip_leading_silence=True)
        assert source.wait_buffered(240, timeout=1)
        assert not sought.render(239).any()
        assert sought.skipped_silence_frames == 0
        assert sought.position_frames == 240
    finally:
        source.close()


def test_zero_skip_preserves_an_internal_pause_arriving_in_a_later_engine_chunk(
    tmp_path: Path,
) -> None:
    source = SpoolingPCMStream(tmp_path / "later-pause.wav")
    try:
        source.append(pcm(*([8192] * 481)))
        renderer = PCMStreamRenderer(source, skip_leading_silence=True)
        renderer.render(240)
        renderer.render(240)
        source.append(pcm(*([0] * 480 + [16384] * 240)))
        source.seal()
        source.finish()
        pause = renderer.render(240)
        assert pause[-1, 0] == 0
        assert renderer.skipped_silence_frames == 0
        assert renderer.position_frames == 720
    finally:
        source.close()


def test_streaming_child_publication_rolls_back_if_parent_duration_write_fails(
    tmp_path: Path,
) -> None:
    import sqlite3  # noqa: PLC0415 - controlled database fault boundary
    from typing import Any  # noqa: PLC0415

    class FaultingConnection(sqlite3.Connection):
        fail_duration = False

        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            if self.fail_duration and "UPDATE utterances SET duration_ms" in sql:
                self.fail_duration = False
                msg = "seeded parent duration write failure"
                raise sqlite3.OperationalError(msg)
            return super().execute(sql, parameters)

    connections: list[FaultingConnection] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=FaultingConnection)
        connections.append(connection)
        return connection

    path = tmp_path / "publication.db"
    store = Store(path, connect=connect)
    clip = store.submit("One child", voice="v", speed=1, spoken_segments=("One child",))
    work = store.claim_for_synthesis()
    assert work is not None
    store.start_streaming(work)
    connections[0].fail_duration = True
    try:
        with pytest.raises(sqlite3.OperationalError, match="seeded parent duration write failure"):
            store.finish_synthesis(work, audio_path="/owned/uncommitted.wav", duration_ms=100)
        child = store.get_segment(clip.id, 0)
        assert child is not None
        assert (child.audio_path, child.duration_ms) == (None, None)
        assert store.synthesis_work_is_active(work)
    finally:
        store.close()
    reopened = Store(path)
    try:
        reopened.recover()
        child = reopened.get_segment(clip.id, 0)
        assert child is not None
        assert (child.state, child.audio_path) == (State.QUEUED, None)
    finally:
        reopened.close()


@pytest.mark.parametrize("composite", [False, True])
def test_failed_live_readiness_write_cannot_strand_completed_synthesis(
    tmp_path: Path, *, composite: bool
) -> None:
    import sqlite3  # noqa: PLC0415 - controlled database fault boundary
    from typing import Any  # noqa: PLC0415

    class FaultingConnection(sqlite3.Connection):
        fail_readiness = False

        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            if self.fail_readiness and "UPDATE utterances SET state" in sql:
                self.fail_readiness = False
                msg = "seeded readiness write failure"
                raise sqlite3.OperationalError(msg)
            return super().execute(sql, parameters)

    connections: list[FaultingConnection] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=FaultingConnection)
        connections.append(connection)
        return connection

    store = Store(tmp_path / "readiness.db", connect=connect)
    try:
        clip = store.submit(
            "Retained source",
            voice="v",
            speed=1,
            spoken_segments=("Retained source",) if composite else None,
        )
        work = store.claim_for_synthesis()
        assert work is not None
        connections[0].fail_readiness = True
        with pytest.raises(sqlite3.OperationalError, match="seeded readiness write failure"):
            store.start_streaming(work)
        store.finish_synthesis(work, audio_path="/owned/complete.wav", duration_ms=100)
        completed = store.get(clip.id)
        assert completed is not None
        assert completed.state is State.READY
        assert completed.duration_ms == 100
        if composite:
            child = store.get_segment(clip.id, 0)
            assert child is not None
            assert (child.state, child.audio_path) == (State.READY, "/owned/complete.wav")
        else:
            assert completed.audio_path == "/owned/complete.wav"
    finally:
        store.close()
