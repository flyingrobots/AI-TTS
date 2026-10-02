# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Chatterbox Turbo's 350M local model, loaded from an explicit asset directory."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from aitts.engine import SynthesisError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import numpy as np
    from numpy.typing import NDArray

_SAMPLE_RATE = 24000
_BATCH_DIMENSIONS = 2
_REQUIRED_FILES = (
    "ve.safetensors",
    "t3_turbo_v1.safetensors",
    "s3gen_meanflow.safetensors",
    "conds.pt",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "added_tokens.json",
    "special_tokens_map.json",
)


def _load_model(directory: Path, device: str) -> Any:  # noqa: ANN401 - upstream is untyped
    from chatterbox.tts_turbo import ChatterboxTurboTTS  # noqa: PLC0415

    return ChatterboxTurboTTS.from_local(directory, device=device)


class ChatterboxEngine:
    """Keep a local Turbo model resident; never discover or fetch assets while speaking.

    Turbo exposes one built-in voice and no generation-speed control. Its native
    output is retained, including its upstream watermark. Playback rate remains
    independently adjustable through the normal transport controls.
    """

    name = "chatterbox"
    is_local = True
    supported_speeds = (1.0,)

    def __init__(
        self,
        directory: Path,
        *,
        device: str = "cpu",
        load_model: Callable[[Path, str], Any] = _load_model,
    ) -> None:
        """Use a complete local ResembleAI/chatterbox-turbo snapshot."""
        self._directory = directory.expanduser().resolve()
        self._device = device
        self._load_model = load_model
        self._model: Any = None
        self._lock = threading.Lock()

    def list_voices(self) -> list[str]:
        """Offer the model's bundled conditioning voice."""
        return ["default"]

    def warmup(self) -> None:
        """Validate the local snapshot, load it and prime a discarded inference."""
        with self._lock:
            if self._model is not None:
                return
            missing = [name for name in _REQUIRED_FILES if not (self._directory / name).is_file()]
            if missing:
                msg = "incomplete local Chatterbox Turbo snapshot; missing: " + ", ".join(missing)
                raise SynthesisError(msg)
            try:
                model = self._load_model(self._directory, self._device)
                self._samples(model.generate("Ready."), model.sr)
            except Exception as exc:
                msg = "Chatterbox Turbo could not load the local model"
                raise SynthesisError(msg) from exc
            self._model = model

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Write the validated native WAV without changing pitch or watermark samples."""
        import soundfile as sf  # noqa: PLC0415

        if voice != "default" or speed != 1.0:
            msg = "Chatterbox uses voice 'default' at generation speed 1; use playback rate instead"
            raise SynthesisError(msg)
        with self._lock:
            if self._model is None:
                msg = "Chatterbox model is not prepared; warmup must finish before synthesis"
                raise SynthesisError(msg)
            try:
                rate = int(self._model.sr)
                samples = self._samples(self._model.generate(text), rate)
                sf.write(str(out_path), samples, rate, format="WAV", subtype="FLOAT")
            except Exception as exc:
                out_path.unlink(missing_ok=True)
                msg = "Chatterbox synthesis failed"
                raise SynthesisError(msg) from exc
            return int(len(samples) * 1000 / rate)

    @staticmethod
    def _samples(audio: Any, rate: int) -> NDArray[np.float32]:  # noqa: ANN401 - tensor boundary
        import numpy as np  # noqa: PLC0415

        samples = np.asarray(audio.detach().cpu().numpy(), dtype=np.float32)
        if samples.ndim == _BATCH_DIMENSIONS and samples.shape[0] == 1:
            samples = samples[0]
        if (
            rate != _SAMPLE_RATE
            or samples.ndim != 1
            or not samples.size
            or not np.isfinite(samples).all()
        ):
            msg = "Chatterbox returned invalid 24 kHz mono audio"
            raise SynthesisError(msg)
        return samples

    def restart(self) -> None:
        """Release and reload from the same local snapshot after synthesis drains."""
        with self._lock:
            self._model = None
        self.warmup()

    def evidence(self, voice: str) -> dict[str, Any]:
        """Fingerprint all local assets needed to reproduce this model and voice."""
        from aitts.adapters.clip_evidence import file_sha256  # noqa: PLC0415

        return {
            "repository": "ResembleAI/chatterbox-turbo",
            "device": self._device,
            "voice": voice,
            "watermark": "upstream output retained",
            "files": {
                name: {
                    "sha256": file_sha256(self._directory / name),
                    "bytes": (self._directory / name).stat().st_size,
                }
                for name in _REQUIRED_FILES
            },
        }
