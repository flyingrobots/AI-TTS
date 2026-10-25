# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Optional MLX Kokoro adapter; assets are prepared before confidential synthesis."""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from aitts.engine import SynthesisError
from aitts.engines.kokoro import VOICES, KokoroAssets, duration_marks
from aitts.streaming import pcm16_frames

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    import numpy as np
    from numpy.typing import NDArray

    from aitts.timing import WordMark


_SAMPLE_RATE = 24000
_FRAME_SAMPLES = 600

log = logging.getLogger(__name__)


def _load_tts(directory: str) -> Any:  # noqa: ANN401 - upstream has no stubs
    if importlib.util.find_spec("en_core_web_sm") is None:
        msg = "English language assets are missing; install en_core_web_sm before model warmup"
        raise SynthesisError(msg)
    from kokoro_mlx import KokoroTTS  # noqa: PLC0415

    return KokoroTTS.from_pretrained(directory)


class KokoroMlxEngine:
    """Render local 24 kHz audio with the optional Apple Silicon backend."""

    name = "kokoro-mlx"
    is_local = True

    def __init__(
        self,
        *,
        assets: KokoroAssets | None = None,
        load_tts: Callable[[str], Any] = _load_tts,
    ) -> None:
        """Retain local asset and upstream loader boundaries without loading weights."""
        self._assets = assets or KokoroAssets(repo_id="mlx-community/Kokoro-82M-bf16")
        self._load_tts = load_tts
        self._model: Any = None
        self._lock = threading.Lock()
        self._files: dict[str, Path] = {}

    def preparation(self) -> tuple[str, float] | None:
        """Report actual first-run asset downloads."""
        return self._assets.fetching

    def list_voices(self) -> list[str]:
        """List the same verified language/voice set as the reference adapter."""
        return list(VOICES)

    def warmup(self) -> None:
        """Prepare weights and language resources before accepting synthesis."""
        with self._lock:
            if self._model is not None:
                return
            names = ["config.json", "kokoro-v1_0.safetensors"] + [
                f"voices/{voice}.safetensors" for voice in VOICES
            ]
            files = {name: Path(self._assets.path(name)) for name in names}
            root = files["config.json"].parent
            if any(path != root / name or not path.is_file() for name, path in files.items()):
                msg = "MLX model files must share one complete local snapshot"
                raise SynthesisError(msg)
            model = self._load_tts(str(root))
            model.generate("Ready.", voice="bm_daniel", speed=1.0, sample_rate=_SAMPLE_RATE)
            self._files = files
            self._model = model

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Write a WAV and report its source duration in milliseconds."""
        import soundfile as sf  # noqa: PLC0415

        samples = self._generate_samples(text, voice, speed)
        sf.write(str(out_path), samples, _SAMPLE_RATE, format="WAV")
        return int(len(samples) / _SAMPLE_RATE * 1000)

    def synthesize_timed(
        self, text: str, voice: str, speed: float, out_path: Path
    ) -> tuple[int, tuple[WordMark, ...]]:
        """Write a WAV and return its duration with the model's predicted token times."""
        import numpy as np  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415

        chunks: list[NDArray[np.float32]] = []
        marks: list[WordMark] = []
        for item in self.stream_synthesize_timed(text, voice, speed, pcm=False):
            if isinstance(item, tuple):
                marks.extend(item)
            else:
                chunks.append(item)
        if not chunks:
            msg = "MLX synthesis failed"
            raise SynthesisError(msg)
        samples = np.concatenate(chunks)
        sf.write(str(out_path), samples, _SAMPLE_RATE, format="WAV")
        return int(len(samples) / _SAMPLE_RATE * 1000), tuple(marks)

    def stream_synthesize(
        self, text: str, voice: str, speed: float
    ) -> Generator[bytes, None, None]:
        """Yield bounded PCM as upstream phoneme chunks finish, under one model lock."""
        with self._lock:
            model = self._prepared_model(voice)
            try:
                for audio in model.generate_stream(
                    text, voice=voice, speed=speed, sample_rate=_SAMPLE_RATE
                ):
                    yield from pcm16_frames(self._validated_samples(audio, _SAMPLE_RATE))
            except Exception as exc:
                msg = "MLX streaming synthesis failed"
                raise SynthesisError(msg) from exc

    def stream_synthesize_timed(
        self, text: str, voice: str, speed: float, *, pcm: bool = True
    ) -> Generator[Any, None, None]:
        """Yield each chunk's token times before its audio, under one model lock.

        Upstream computes per-phoneme durations inside ``forward`` and keeps
        them. For the length of this call, the duration projection and the
        G2P are observed (not replaced): their outputs are recorded and the
        same values flow on, so the audio path is unchanged. Any mismatch in
        that observation costs the marks, never the audio.
        """
        with self._lock:
            model = self._prepared_model(voice)
            try:
                with _DurationObserver(model, voice) as observer:
                    for audio in model.generate_stream(
                        text, voice=voice, speed=speed, sample_rate=_SAMPLE_RATE
                    ):
                        samples = self._validated_samples(audio, _SAMPLE_RATE)
                        marks = observer.marks(len(samples))
                        if marks:
                            yield marks
                        if pcm:
                            yield from pcm16_frames(samples)
                        else:
                            yield samples
            except SynthesisError:
                raise
            except Exception as exc:
                msg = "MLX streaming synthesis failed"
                raise SynthesisError(msg) from exc

    def _prepared_model(self, voice: str) -> Any:  # noqa: ANN401 - untyped optional upstream
        if voice not in VOICES:
            msg = f"unknown MLX voice {voice!r}"
            raise SynthesisError(msg)
        if self._model is None:
            msg = "MLX model is not prepared; warmup must finish before synthesis"
            raise SynthesisError(msg)
        return self._model

    def _generate_samples(self, text: str, voice: str, speed: float) -> NDArray[np.float32]:
        with self._lock:
            model = self._prepared_model(voice)
            try:
                result = model.generate(text, voice=voice, speed=speed, sample_rate=_SAMPLE_RATE)
            except Exception as exc:
                msg = "MLX synthesis failed"
                raise SynthesisError(msg) from exc
            return self._validated_samples(result.audio, result.sample_rate)

    @staticmethod
    def _validated_samples(audio: Any, sample_rate: int) -> NDArray[np.float32]:  # noqa: ANN401 - untyped upstream arrays
        import numpy as np  # noqa: PLC0415

        samples = np.asarray(audio, dtype=np.float32)
        if sample_rate != _SAMPLE_RATE or samples.ndim != 1 or not samples.size:
            msg = "MLX returned invalid audio format"
            raise SynthesisError(msg)
        if not np.isfinite(samples).all():
            msg = "MLX returned non-finite audio"
            raise SynthesisError(msg)
        return samples

    def restart(self) -> None:
        """Release and reload after the daemon drains in-flight synthesis."""
        with self._lock:
            self._model = None
        self.warmup()

    def evidence(self, voice: str) -> dict[str, Any]:
        """Fingerprint the actual local model and selected voice."""
        from aitts.adapters.clip_evidence import file_sha256  # noqa: PLC0415

        names = ("config.json", "kokoro-v1_0.safetensors", f"voices/{voice}.safetensors")
        return {
            "repository": self._assets.repo_id,
            "device": "Metal",
            "files": {
                name: {
                    "sha256": file_sha256(self._files[name]),
                    "bytes": self._files[name].stat().st_size,
                }
                for name in names
            },
        }


_ABSENT = object()


class _DurationObserver:
    """Record kokoro-mlx's per-phoneme durations and G2P tokens for one call.

    Bound to the pinned ``kokoro-mlx`` 0.1.2 internals: ``KokoroTTS._model``
    (``forward`` and ``predictor.duration_proj``) and the voice's phonemizer
    ``_g2p``. Instance attributes shadow the originals and are removed on
    exit. If any of them is absent the observer records nothing.
    """

    def __init__(self, tts: Any, voice: str) -> None:  # noqa: ANN401 - untyped upstream
        self._tts = tts
        self._voice = voice
        self._patched: list[tuple[Any, str, object]] = []
        self._tokens: dict[str, Any] = {}
        self._calls: list[dict[str, Any]] = []
        self._offset_ms = 0.0
        self._consumed = 0

    def __enter__(self) -> Self:
        with contextlib.suppress(AttributeError, TypeError, KeyError, ValueError):
            model = self._tts._model  # noqa: SLF001 - pinned upstream internals
            phonemizer = self._tts._get_phonemizer(None, self._voice)  # noqa: SLF001
            original_g2p = phonemizer._g2p  # noqa: SLF001
            original_forward = model.forward
            original_projection = model.predictor.duration_proj

            def g2p(text: str) -> Any:  # noqa: ANN401 - upstream G2P result
                result = original_g2p(text)
                if isinstance(result, tuple) and len(result) == 2 and result[1] is not None:  # noqa: PLR2004
                    self._tokens[str(result[0] or "")] = result[1]
                return result

            def forward(phonemes: str, ref_s: Any, speed: float = 1.0) -> Any:  # noqa: ANN401
                self._calls.append({"phonemes": phonemes, "speed": speed})
                return original_forward(phonemes, ref_s, speed)

            def projection(features: Any) -> Any:  # noqa: ANN401 - mlx array
                output = original_projection(features)
                if self._calls:
                    self._calls[-1]["durations"] = output
                return output

            for owner, name, replacement in (
                (phonemizer, "_g2p", g2p),
                (model, "forward", forward),
                (model.predictor, "duration_proj", projection),
            ):
                previous = vars(owner).get(name, _ABSENT)
                object.__setattr__(owner, name, replacement)
                self._patched.append((owner, name, previous))
        return self

    def __exit__(self, *_exc: object) -> None:
        # An instance attribute (the G2P) is put back; a shadowed class or
        # module-dict lookup (``forward``, ``duration_proj``) is uncovered again.
        for owner, name, previous in reversed(self._patched):
            with contextlib.suppress(AttributeError):
                if previous is _ABSENT:
                    object.__delattr__(owner, name)
                else:
                    object.__setattr__(owner, name, previous)
        self._patched.clear()

    def marks(self, sample_count: int) -> tuple[WordMark, ...]:
        """Return marks for the chunk just rendered, on the clip clock.

        The frame total must reproduce the chunk's sample count exactly;
        otherwise the observation does not describe this audio and nothing is
        reported. Never raises: timing is an aid, the audio is the product.
        """
        offset = self._offset_ms
        self._offset_ms += sample_count / _SAMPLE_RATE * 1000
        calls = self._calls[self._consumed :]
        self._consumed = len(self._calls)
        try:
            if len(calls) == 1:
                tokens = self._tokens.get(calls[0]["phonemes"])
                durations = _frame_durations(calls[0].get("durations"), calls[0]["speed"])
                if (
                    tokens is not None
                    and durations is not None
                    and sum(durations) * _FRAME_SAMPLES == sample_count
                ):
                    return duration_marks(tokens, durations, offset)
        except Exception:  # noqa: BLE001 - an observation failure costs only the marks
            log.info("event=mlx_duration_observation_failed")
            return ()
        log.info("event=mlx_duration_observation_unmatched")
        return ()


def _frame_durations(output: Any, speed: float) -> list[int] | None:  # noqa: ANN401 - mlx array
    """Reproduce upstream ``forward``'s frame rounding from the projection output.

    Upstream: ``max(1, clip(round(sum(sigmoid(proj), -1) / speed), 0))``. MLX
    is used when present so the arithmetic (dtype included) is upstream's own.
    """
    if output is None:
        return None
    try:
        import mlx.core as mx  # noqa: PLC0415 - optional Apple Silicon dependency
    except ImportError:
        import numpy as np  # noqa: PLC0415

        values = np.asarray(output.tolist() if hasattr(output, "tolist") else output, dtype=float)
        frames = (1 / (1 + np.exp(-values))).sum(axis=-1) / speed
        return [int(v) for v in np.maximum(np.clip(np.round(frames), 0, None), 1).reshape(-1)]
    frames = mx.sigmoid(output).sum(axis=-1) / speed
    rounded = mx.maximum(mx.clip(mx.round(frames), 0, None), 1).astype(mx.int32)
    listed = rounded.reshape(-1).tolist()
    return [int(value) for value in listed] if isinstance(listed, list) else None
