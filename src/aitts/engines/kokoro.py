# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Kokoro-82M adapter: the reference PyTorch pipeline, held warm.

Chosen in docs/design/engine-evaluation.md: Apache-2.0, fully local, fast
enough on Apple Silicon that the queue design, not the engine, governs
perceived responsiveness. One pipeline is kept per language (the first letter
of a Kokoro voice id names its language).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from aitts.engine import SynthesisError

if TYPE_CHECKING:
    from pathlib import Path

_SAMPLE_RATE = 24000

# Kokoro v1.0 English voices (hexgrad/Kokoro-82M). The daemon enumerates
# these; clients and UIs must never hardcode a voice.
VOICES: tuple[str, ...] = (
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
)


class KokoroEngine:
    """Speaks through the ``kokoro`` package's KPipeline."""

    name = "kokoro"
    is_local = True

    def __init__(self) -> None:
        """Create the adapter; the model loads on warmup or first use."""
        self._pipelines: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _pipeline(self, voice: str) -> Any:  # noqa: ANN401 - kokoro ships no type stubs
        lang_code = voice[0]
        with self._lock:
            pipeline = self._pipelines.get(lang_code)
            if pipeline is None:
                try:
                    from kokoro import KPipeline  # noqa: PLC0415 - import on first use
                except ImportError as exc:  # pragma: no cover - install-time problem
                    msg = (
                        "the 'kokoro' package is not installed; "
                        "install ai-tts with the [kokoro] extra"
                    )
                    raise SynthesisError(msg) from exc
                pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
                self._pipelines[lang_code] = pipeline
        return pipeline

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Render ``text`` to a WAV at ``out_path``; return its duration in ms."""
        import numpy as np  # noqa: PLC0415 - keep numpy out of module import time
        import soundfile as sf  # noqa: PLC0415

        pipeline = self._pipeline(voice)
        chunks: list[Any] = []
        try:
            for result in pipeline(text, voice=voice, speed=speed):
                audio = result.audio if hasattr(result, "audio") else result[-1]
                if audio is not None:
                    chunks.append(audio.numpy() if hasattr(audio, "numpy") else audio)
        except Exception as exc:
            raise SynthesisError(str(exc)) from exc
        if not chunks:
            msg = "the engine produced no audio"
            raise SynthesisError(msg)
        samples = np.concatenate(chunks)
        sf.write(str(out_path), samples, _SAMPLE_RATE, format="WAV")
        return int(len(samples) / _SAMPLE_RATE * 1000)

    def list_voices(self) -> list[str]:
        """Enumerate the known Kokoro voices."""
        return list(VOICES)

    def warmup(self) -> None:
        """Load the default-language pipeline so first synthesis is not cold."""
        self._pipeline("bm_daniel")
