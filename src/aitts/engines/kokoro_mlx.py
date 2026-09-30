# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Optional MLX Kokoro adapter; assets are prepared before confidential synthesis."""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aitts.engine import SynthesisError
from aitts.engines.kokoro import VOICES, KokoroAssets

if TYPE_CHECKING:
    from collections.abc import Callable


_SAMPLE_RATE = 24000


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
        import numpy as np  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415

        if voice not in VOICES:
            msg = f"unknown MLX voice {voice!r}"
            raise SynthesisError(msg)
        with self._lock:
            if self._model is None:
                msg = "MLX model is not prepared; warmup must finish before synthesis"
                raise SynthesisError(msg)
            try:
                result = self._model.generate(
                    text, voice=voice, speed=speed, sample_rate=_SAMPLE_RATE
                )
            except Exception as exc:
                msg = "MLX synthesis failed"
                raise SynthesisError(msg) from exc
            samples = np.asarray(result.audio, dtype=np.float32)
            if result.sample_rate != _SAMPLE_RATE or samples.ndim != 1 or not samples.size:
                msg = "MLX returned invalid audio format"
                raise SynthesisError(msg)
            if not np.isfinite(samples).all():
                msg = "MLX returned non-finite audio"
                raise SynthesisError(msg)
            sf.write(str(out_path), samples, _SAMPLE_RATE, format="WAV")
            return int(len(samples) / _SAMPLE_RATE * 1000)

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
