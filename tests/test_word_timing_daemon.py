# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Word timing through the daemon: synthesis, storage, ``timings`` and position events."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import tempfile
import threading
import wave
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import ContentFormat, State
from aitts.playback import FakeSink
from aitts.segmentation import prepare_speech_segments
from aitts.streaming import SpoolingPCMStream
from aitts.timing import ClipTimings, TimingSource, WordMark, word_spans
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "word-timing protocol in docs/design/architecture.md section 5: timings op and "
        "playback_position events index the exact submitted text on the source-audio clock"
    ),
]

_WORD_MS = 100


def _write_wav(path: Path, duration_ms: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x01\x00" * (24 * duration_ms))


def _even_marks(text: str) -> tuple[WordMark, ...]:
    """One engine token per written word, 100 ms each, from the clip's start."""
    return tuple(
        WordMark(text[start:end], i * _WORD_MS, (i + 1) * _WORD_MS)
        for i, (start, end) in enumerate(word_spans(text))
    )


class TimedFileEngine(FakeEngine):
    """File-only engine that reports a token per word, like Kokoro does."""

    def __init__(self) -> None:
        super().__init__(voices=["bm_daniel"])

    def synthesize_timed(
        self, text: str, voice: str, speed: float, out_path: Path
    ) -> tuple[int, tuple[WordMark, ...]]:
        del voice, speed
        duration = len(word_spans(text)) * _WORD_MS
        _write_wav(out_path, duration)
        return duration, _even_marks(text)


class GatedTimedStreamingEngine(FakeEngine):
    """Streams the first half's marks and PCM, then waits to be released."""

    def __init__(self) -> None:
        super().__init__(voices=["bm_daniel"])
        self.first_half = threading.Event()
        self.release = threading.Event()

    def stream_synthesize(self, text: str, voice: str, speed: float) -> Iterator[bytes]:
        for item in self.stream_synthesize_timed(text, voice, speed):
            if isinstance(item, bytes):
                yield item

    def stream_synthesize_timed(
        self, text: str, voice: str, speed: float
    ) -> Iterator[bytes | tuple[WordMark, ...]]:
        del voice, speed
        marks = _even_marks(text)
        half = len(marks) // 2
        yield marks[:half]
        yield b"\x01\x00" * (24 * _WORD_MS * half)
        self.first_half.set()
        if not self.release.wait(3):
            msg = "test did not release the stream"
            raise TimeoutError(msg)
        yield marks[half:]
        yield b"\x01\x00" * (24 * _WORD_MS * (len(marks) - half))


class StreamingFakeSink(FakeSink):
    def __init__(self) -> None:
        super().__init__()
        self.stream_started = asyncio.Event()

    def start_stream(
        self, source: SpoolingPCMStream, *, artifact_id: str, position_ms: int = 0
    ) -> None:
        del source
        super().start(Path(artifact_id), position_ms=position_ms)
        self.stream_started.set()


@contextlib.asynccontextmanager
async def running(daemon: Daemon) -> AsyncIterator[Daemon]:
    await daemon.start()
    try:
        yield daemon
    finally:
        await daemon.stop()


@pytest.fixture
def socket_dir() -> Iterator[Path]:
    # A short private directory: tmp_path can exceed the Unix socket path limit.
    path = Path(tempfile.mkdtemp(prefix="aitts-wt-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


async def test_streaming_clip_reports_engine_words_while_still_generating(
    tmp_path: Path, socket_dir: Path
) -> None:
    text = "Owned streaming source speaks these eight words aloud"
    engine = GatedTimedStreamingEngine()
    sink = StreamingFakeSink()
    daemon = Daemon(home=tmp_path, engine=engine, sink=sink, socket_path=socket_dir / "s")
    clip = daemon.store.submit(text, voice="bm_daniel", speed=1.0)
    async with running(daemon):
        try:
            assert await asyncio.to_thread(engine.first_half.wait, 2)
            await asyncio.wait_for(sink.stream_started.wait(), timeout=2)
            sink.advance_to(250)  # inside the third word, "source"

            live = daemon.position_events(("codepoint",))["codepoint"]
            partial = await daemon.dispatch({"op": "timings", "id": clip.id})

            assert live["state"] == "playing"
            assert live["timing"] == "engine"
            assert live["word_index"] == 2
            assert text[live["char_start"] : live["char_end"]] == "source"
            (segment,) = partial["segments"]
            assert segment["complete"] is False
            assert [w[0] for w in segment["words"]] == [0, 100, 200, 300, None, None, None, None]
        finally:
            engine.release.set()
        await wait_for(lambda: daemon.store.timings(clip.id) is not None)
        final = await daemon.dispatch({"op": "timings", "id": clip.id})

    (segment,) = final["segments"]
    assert segment["complete"] is True
    assert segment["timing"] == "engine"
    assert [w[0] for w in segment["words"]] == [i * _WORD_MS for i in range(8)]
    assert [text[w[2] : w[3]] for w in segment["words"]] == text.split()
    assert segment["sentences"] == [[0, len(text), 0, 7]]


async def test_engine_without_timing_gets_audio_anchored_estimate(
    tmp_path: Path, socket_dir: Path
) -> None:
    text = "Nothing here reports times. The daemon estimates them."
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"], duration_ms=2000),
        sink=FakeSink(),
        socket_path=socket_dir / "s",
    )
    clip = daemon.store.submit(text, voice="bm_daniel", speed=1.0)
    async with running(daemon):
        await wait_for(lambda: daemon.store.timings(clip.id) is not None)
        reply = await daemon.dispatch({"op": "timings", "id": clip.id})
        stored = ClipTimings.decode(daemon.store.timings(clip.id))

    assert stored is not None
    assert stored.source is TimingSource.ESTIMATED
    (segment,) = reply["segments"]
    assert segment["timing"] == "estimated"
    assert len(segment["words"]) == len(text.split())
    assert [text[w[2] : w[3]] for w in segment["words"]] == text.split()
    assert [s[2:] for s in segment["sentences"]] == [[0, 3], [4, 7]]


def _document() -> str:
    first = " ".join(f"alpha{i}" for i in range(30)) + "."
    second = "Emoji \U0001f600 marks the second paragraph " + " ".join(
        f"beta{i}" for i in range(30)
    )
    # Front matter repeats spoken words; offsets must still land in the body.
    return f"---\ntitle: Heading alpha0\n---\n# Heading\n\n{first}\n\n{second}."


async def _read_event(reader: asyncio.StreamReader, predicate: Any) -> dict[str, Any]:
    async with asyncio.timeout(3):
        while True:
            event: dict[str, Any] = json.loads(await reader.readline())
            if event.get("event") == "playback_position" and predicate(event):
                return event


async def test_socket_followers_receive_words_in_their_offset_unit_across_segments(
    tmp_path: Path, socket_dir: Path
) -> None:
    source = _document()
    segments = prepare_speech_segments(source, content_format=ContentFormat.MARKDOWN)
    assert len(segments) >= 2
    sink = FakeSink()
    daemon = Daemon(
        home=tmp_path, engine=TimedFileEngine(), sink=sink, socket_path=socket_dir / "s"
    )
    clip = daemon.store.submit(source, voice="bm_daniel", speed=1.0, spoken_segments=segments)
    async with running(daemon):
        reader, writer = await asyncio.open_unix_connection(str(daemon.socket_path))
        try:
            writer.write(b'{"op":"subscribe","playback_position":true,"offset_unit":"utf16"}\n')
            ack = json.loads(await reader.readline())
            assert ack == {
                "ok": True,
                "subscribed": True,
                "playback_position": {"v": 1, "offset_unit": "utf16"},
            }
            await wait_for(
                lambda: (u := daemon.store.get(clip.id)) is not None and u.state is State.PLAYING
            )
            first = await _read_event(reader, lambda e: e["state"] == "playing")
            assert first["segment_index"] == 0
            sink.finish_current()  # segment 0 reaches its end; segment 1 starts at 0
            await wait_for(lambda: sink.started and len(sink.started) >= 2)
            sink.advance_to(150)  # second word of segment 1: the emoji
            event = await _read_event(
                reader, lambda e: e["segment_index"] == 1 and e["word_index"] == 1
            )
            described = await daemon.dispatch({"op": "timings", "id": clip.id, "segment": 0})
        finally:
            writer.close()
            await writer.wait_closed()

    (opening,) = described["segments"]
    body = source.index("# Heading")
    assert opening["source_start"] == body + 2
    assert opening["words"][1][2] == source.index("alpha0", body)
    utf16 = source.encode("utf-16-le")
    spoken = utf16[event["char_start"] * 2 : event["char_end"] * 2].decode("utf-16-le")
    assert spoken == "\U0001f600"
    assert event["timing"] == "engine"
    assert event["offset_unit"] == "utf16"
    sentence = utf16[event["sentence_start"] * 2 : event["sentence_end"] * 2].decode("utf-16-le")
    assert sentence.startswith("Emoji")
    assert sentence.endswith("beta29.")


async def test_timings_requests_are_validated(tmp_path: Path, socket_dir: Path) -> None:
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(),
        socket_path=socket_dir / "s",
    )
    async with running(daemon):
        reader, writer = await asyncio.open_unix_connection(str(daemon.socket_path))
        try:
            replies = []
            for request in (
                {"op": "timings"},
                {"op": "timings", "id": "utt_missing"},
                {"op": "timings", "id": "utt_missing", "offset_unit": "bytes"},
                {"op": "timings", "id": "utt_missing", "segment": -1},
                {"op": "subscribe", "playback_position": True, "offset_unit": "bytes"},
            ):
                writer.write(json.dumps(request).encode() + b"\n")
                replies.append(json.loads(await reader.readline()))
        finally:
            writer.close()
            await writer.wait_closed()

    assert [reply["error"]["type"] for reply in replies] == [
        "bad_request",
        "not_found",
        "bad_request",
        "bad_request",
        "bad_request",
    ]
