# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Bounded PCM transport with a disk spool for long holds and backward seeks.

The wire format between streaming engines and playback is signed little-endian
16-bit mono PCM at 24 kHz. Device callbacks read only the bounded ring; a feeder
thread handles disk reads. The producer never waits for playback to consume.
"""

from __future__ import annotations

import math
import os
import threading
import time
import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    from numpy.typing import NDArray

SAMPLE_RATE = 24_000
FRAME_BYTES = 2
# A transport close fades over 20 ms, as the file sink's soft close does.
SOFT_FADE_FRAMES = SAMPLE_RATE // 50
_WAV_HEADER_BYTES = 44


class CircularAudioBuffer:
    """A bounded mono PCM ring; synchronization belongs to its owner."""

    def __init__(self, capacity_frames: int) -> None:
        """Allocate exactly ``capacity_frames`` samples."""
        if capacity_frames < 1:
            msg = "PCM buffer capacity must be positive"
            raise ValueError(msg)
        self._data = bytearray(capacity_frames * FRAME_BYTES)
        self._head = 0
        self.frames = 0
        self.capacity_frames = capacity_frames

    def write(self, pcm: bytes) -> int:
        """Append as many whole frames as fit; return the accepted frame count."""
        if len(pcm) % FRAME_BYTES:
            msg = "PCM chunks must contain whole 16-bit samples"
            raise ValueError(msg)
        frames = min(len(pcm) // FRAME_BYTES, self.capacity_frames - self.frames)
        count = frames * FRAME_BYTES
        tail = (self._head + self.frames * FRAME_BYTES) % len(self._data)
        first = min(count, len(self._data) - tail)
        self._data[tail : tail + first] = pcm[:first]
        self._data[: count - first] = pcm[first:count]
        self.frames += frames
        return frames

    def read(self, frames: int) -> bytes:
        """Consume up to ``frames`` available samples, without waiting."""
        if frames < 0:
            msg = "PCM frame count must be nonnegative"
            raise ValueError(msg)
        count = min(frames, self.frames) * FRAME_BYTES
        first = min(count, len(self._data) - self._head)
        result = bytes(self._data[self._head : self._head + first] + self._data[: count - first])
        self._head = (self._head + count) % len(self._data)
        self.frames -= count // FRAME_BYTES
        return result

    def clear(self) -> None:
        """Discard buffered samples for an explicit source seek."""
        self._head = 0
        self.frames = 0


@dataclass(frozen=True)
class PCMRead:
    """Available samples and source position; silence is never source progress."""

    pcm: bytes
    position_frames: int
    ended: bool
    error: str | None


class SpoolingPCMStream:
    """Spool generated frames and feed a bounded callback-facing PCM ring.

    ``seal`` finalizes the WAV but does not signal playback completion. The
    synthesis owner must validate/publish the artifact and commit its metadata
    before calling ``finish``. This prevents playback finishing ahead of cache
    publication. A consumer can seek into the spool after arbitrarily long holds.
    """

    def __init__(
        self, path: Path, *, capacity_frames: int = SAMPLE_RATE, _cached: bool = False
    ) -> None:
        """Open an owned candidate WAV and start its disk-to-ring feeder."""
        self._condition = threading.Condition()
        self._writer_lock = threading.RLock()
        self._ring = CircularAudioBuffer(capacity_frames)
        self._file = path.open("rb" if _cached else "w+b", buffering=0)
        self._cached_reader: wave.Wave_read | None = None
        self._wav: wave.Wave_write | None = None
        if _cached:
            try:
                self._cached_reader = wave.open(self._file, "rb")  # noqa: SIM115 - feeder owns reader
                params = self._cached_reader.getparams()
                if (params.nchannels, params.sampwidth, params.framerate) != (
                    1,
                    FRAME_BYTES,
                    SAMPLE_RATE,
                ):
                    msg = "cached WAV needs the general file-output path"
                    raise ValueError(msg)  # noqa: TRY301 - close the owned file on format rejection
                self._available = params.nframes
            except (wave.Error, EOFError, ValueError) as exc:
                self._file.close()
                msg = "cached WAV is not streaming PCM"
                raise ValueError(msg) from exc
        else:
            os.fchmod(self._file.fileno(), 0o600)
            self._wav = wave.open(self._file, "wb")  # noqa: SIM115 - owned until seal/close
            self._wav.setnchannels(1)
            self._wav.setsampwidth(FRAME_BYTES)
            self._wav.setframerate(SAMPLE_RATE)
            self._available = 0
        self._fed = 0
        self._position = 0
        self._epoch = 0
        self._sealed = _cached
        self._finished = _cached
        self._closed = False
        self._owners = 1
        self._error: str | None = None
        self._reader_fd = -1 if _cached else os.dup(self._file.fileno())
        self._feeder = threading.Thread(target=self._feed, name="aitts.pcm-feeder", daemon=True)
        self._feeder.start()

    @classmethod
    def from_cached(cls, path: Path) -> SpoolingPCMStream:
        """Feed an existing compatible WAV without rewriting its bytes or headers."""
        return cls(path, _cached=True)

    def append(self, pcm: bytes) -> None:
        """Write one engine chunk without waiting for playback or ring space."""
        with self._writer_lock:
            if len(pcm) % FRAME_BYTES:
                msg = "PCM chunks must contain whole 16-bit samples"
                raise ValueError(msg)
            if self._sealed or self._closed:
                msg = "PCM production is closed"
                raise RuntimeError(msg)
            assert self._wav is not None  # noqa: S101 - production is writable until sealed
            self._wav.writeframesraw(pcm)
            with self._condition:
                prior_end = self._available
                self._available += len(pcm) // FRAME_BYTES
                # The live path goes straight into the ring. Overflow stays in
                # the complete spool; only that backlog or a seek needs disk reads.
                if self._fed == prior_end:
                    self._fed += self._ring.write(pcm)
                self._condition.notify_all()

    def seal(self) -> int:
        """Finalize the cache WAV and return its duration in milliseconds."""
        with self._writer_lock:
            if not self._sealed and self._wav is not None:
                self._wav.close()
                self._sealed = True
            return self._available * 1000 // SAMPLE_RATE

    def finish(self, *, error: str | None = None) -> None:
        """Release EOF only after durable publication, or report generation failure."""
        with self._condition:
            self._error = error or self._error
            self._finished = True
            self._condition.notify_all()

    def read(self, frames: int) -> PCMRead:
        """Read only memory; an underflow returns no samples and no false EOF."""
        with self._condition:
            pcm = self._ring.read(frames)
            self._position += len(pcm) // FRAME_BYTES
            ended = self._finished and self._position >= self._available
            self._condition.notify_all()
            return PCMRead(pcm, self._position, ended, self._error)

    def seek(self, position_frames: int) -> None:
        """Move the sole playback reader without moving or blocking synthesis."""
        if position_frames < 0:
            msg = "PCM position must be nonnegative"
            raise ValueError(msg)
        with self._condition:
            if position_frames == self._position:
                return
            self._epoch += 1
            self._ring.clear()
            self._position = position_frames
            self._fed = position_frames
            self._condition.notify_all()

    def wait_buffered(self, frames: int, *, timeout: float) -> bool:
        """Bound initial prefill; return false if the requested audio is unavailable."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._ring.frames < frames and not self._closed and self._error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return self._ring.frames >= frames

    def retain(self) -> None:
        """Keep the source alive for a playback session after publication."""
        with self._condition:
            if self._closed:
                msg = "PCM source is closed"
                raise RuntimeError(msg)
            self._owners += 1

    def release(self) -> None:
        """Release one producer or playback owner."""
        with self._condition:
            self._owners -= 1
            close = self._owners == 0
        if close:
            self.close()

    def close(self) -> None:
        """Stop the feeder and release this stream's owned file descriptors."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._feeder.join(timeout=2)
        self.seal()
        with self._writer_lock:
            self._file.close()

    def _feed(self) -> None:
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: (
                            self._closed
                            or (
                                self._fed < self._available
                                and self._ring.frames < self._ring.capacity_frames
                            )
                        )
                    )
                    if self._closed:
                        return
                    offset, epoch = self._fed, self._epoch
                    count = min(
                        self._available - offset, self._ring.capacity_frames - self._ring.frames
                    )
                if self._cached_reader is not None:
                    self._cached_reader.setpos(offset)
                    pcm = self._cached_reader.readframes(count)
                else:
                    pcm = os.pread(
                        self._reader_fd,
                        count * FRAME_BYTES,
                        _WAV_HEADER_BYTES + offset * FRAME_BYTES,
                    )
                if len(pcm) != count * FRAME_BYTES:
                    msg = "PCM spool returned incomplete frames"
                    raise OSError(msg)  # noqa: TRY301 - feed errors are reported to the consumer
                with self._condition:
                    if epoch == self._epoch and offset == self._fed:
                        self._fed += self._ring.write(pcm)
                        self._condition.notify_all()
        except OSError as exc:
            self.finish(error=str(exc))
        finally:
            if self._cached_reader is not None:
                self._cached_reader.close()
            else:
                os.close(self._reader_fd)


class StreamingRegistry:
    """Share in-flight sources between the synthesis worker and serialized player."""

    def __init__(self) -> None:
        """Create an empty, process-local registry."""
        self._lock = threading.Lock()
        self._sources: dict[str, SpoolingPCMStream] = {}
        self._closed = False

    def add(self, artifact_id: str, source: SpoolingPCMStream) -> None:
        """Register a producer-owned source before advertising readiness."""
        with self._lock:
            if self._closed:
                source.close()
                msg = "streaming registry is closed"
                raise RuntimeError(msg)
            self._sources[artifact_id] = source

    def get(self, artifact_id: str) -> SpoolingPCMStream | None:
        """Return the live source while its cache artifact is incomplete."""
        with self._lock:
            return self._sources.get(artifact_id)

    def finish(self, artifact_id: str, *, error: str | None = None) -> None:
        """Unregister a completed producer; active playback retains its own owner."""
        with self._lock:
            source = self._sources.pop(artifact_id, None)
        if source is not None:
            source.finish(error=error)
            source.release()

    def close(self) -> None:
        """Abort unpublished producers when the daemon shuts down."""
        with self._lock:
            self._closed = True
            sources = list(self._sources.values())
            self._sources.clear()
        for source in sources:
            source.finish(error="daemon stopped during generation")
            source.release()


class PCMStreamRenderer:
    """Turn ring samples into device blocks without disk I/O or source-clock drift."""

    def __init__(
        self,
        source: SpoolingPCMStream,
        *,
        position_frames: int = 0,
        skip_leading_silence: bool = False,
    ) -> None:
        """Start the sole reader at an explicit source offset."""
        import numpy as np  # noqa: PLC0415 - keep numpy off source transport imports

        self.source = source
        source.seek(position_frames)
        self.position_frames = float(position_frames)
        self._pending = np.empty(0, dtype=np.float32)
        self._phase = 0.0
        self._last = 0.0
        self._was_silent = True
        self.ended = False
        self.error: str | None = None
        self.underruns = 0
        self.skipped_silence_frames = 0
        self._trim_leading = skip_leading_silence and position_frames == 0

    def render(self, frames: int, *, rate: float = 1.0) -> NDArray[np.float32]:
        """Fill missing audio with a short decay to silence, without consuming time."""
        import numpy as np  # noqa: PLC0415 - keep numpy off source transport imports

        output = np.zeros((frames, 1), dtype=np.float32)
        needed = max(0, math.ceil(frames * rate + self._phase) + 1 - len(self._pending))
        if self._trim_leading:
            # One bounded memory read per callback. Never scan disk, and never
            # skip an intentional pause once the first nonzero sample is seen.
            needed = max(needed, SAMPLE_RATE)
        read = self.source.read(needed)
        self.error = read.error
        if self.error is not None:
            return self.stop_block(frames)
        if read.pcm:
            samples = np.frombuffer(read.pcm, dtype="<i2")
            if self._trim_leading:
                nonzero = np.flatnonzero(samples)
                skipped = int(nonzero[0]) if nonzero.size else len(samples)
                self.position_frames += skipped
                self.skipped_silence_frames += skipped
                samples = samples[skipped:]
                self._trim_leading = not nonzero.size and not read.ended
            self._pending = np.concatenate((self._pending, samples / 32768.0))
        usable = len(self._pending) - self._phase - (0 if read.ended else 1)
        count = min(frames, max(0, math.ceil(usable / rate)))
        if count:
            positions = self._phase + np.arange(count) * rate
            output[:count, 0] = np.interp(positions, np.arange(len(self._pending)), self._pending)
            if self._was_silent:
                ramp = min(count, 120)
                output[:ramp, 0] *= np.linspace(0.0, 1.0, ramp)
            advanced = min(count * rate, len(self._pending) - self._phase)
            self._phase += advanced
            self.position_frames += advanced
            consumed = int(self._phase)
            self._pending = self._pending[consumed:]
            self._phase -= consumed
        if count < frames:
            last = float(output[count - 1, 0]) if count else self._last
            ramp = min(frames - count, 120)
            output[count : count + ramp, 0] = np.linspace(last, 0.0, ramp)
            if not read.ended and self.error is None:
                self.underruns += 1
        self._was_silent = count < frames
        self._last = float(output[-1, 0])
        self.ended = read.ended and len(self._pending) == 0
        return output

    def close_block(self, frames: int, *, rate: float = 1.0) -> NDArray[np.float32]:
        """Fade what would play next to silence, without advancing source position.

        This is the file sink's soft close on the callback path: the next
        ``SOFT_FADE_FRAMES`` of source (or the whole block, if shorter) under a
        raised cosine, then silence. The read-ahead comes from memory only, and
        a later renderer seeks back to the unchanged playhead, so resumption
        repeats nothing.
        """
        import numpy as np  # noqa: PLC0415 - keep numpy off source transport imports

        output = np.zeros((frames, 1), dtype=np.float32)
        fade = min(frames, SOFT_FADE_FRAMES)
        # Underrun silence or untrimmed leading zeros: nothing is sounding.
        if self._was_silent or self._trim_leading:
            self._last = 0.0
            return output
        needed = max(0, math.ceil(fade * rate + self._phase) + 1 - len(self._pending))
        read = self.source.read(needed)
        if read.error is not None:
            return self.stop_block(frames)
        if read.pcm:
            samples = np.frombuffer(read.pcm, dtype="<i2") / 32768.0
            self._pending = np.concatenate((self._pending, samples))
        usable = len(self._pending) - self._phase - (0 if read.ended else 1)
        count = min(fade, max(0, math.ceil(usable / rate)))
        ahead = np.full(fade, self._last, dtype=np.float32)
        if count:
            positions = self._phase + np.arange(count) * rate
            ahead[:count] = np.interp(positions, np.arange(len(self._pending)), self._pending)
            # Near the end there is less source than fade. Hold the last
            # sample so the envelope, not the edge of the source, reaches zero.
            ahead[count:] = ahead[count - 1]
        gain = 0.5 * (1 + np.cos(np.linspace(0.0, math.pi, fade)))
        output[:fade, 0] = ahead * gain
        self._last = 0.0
        return output

    def stop_block(self, frames: int) -> NDArray[np.float32]:
        """End the device stream at silence without advancing source position."""
        import numpy as np  # noqa: PLC0415 - keep numpy off source transport imports

        output = np.zeros((frames, 1), dtype=np.float32)
        ramp = min(frames, 120)
        output[:ramp, 0] = np.linspace(self._last, 0.0, ramp)
        self._last = 0.0
        return output
