# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Kokoro-82M adapter: the reference PyTorch pipeline, held warm.

Chosen in docs/design/engine-evaluation.md: Apache-2.0, fully local, fast
enough on Apple Silicon that the queue design, not the engine, governs
perceived responsiveness. One pipeline is kept per language (the first letter
of a Kokoro voice id names its language).

"Fully local" has to include how the weights are found. Left to its defaults
the upstream package resolves its config, its weights, and *each voice pack*
through the model host every time it loads one, which reaches the network
even when every file is already cached. For a daemon whose text is
client-confidential that is a metadata leak — the request names the exact
voice and the moment it spoke — and it makes the daemon useless offline.
:class:`KokoroAssets` therefore resolves from the local cache first and only
fetches a genuinely absent file.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Protocol

from aitts.engine import SynthesisError

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

_SAMPLE_RATE = 24000
_DEFAULT_REPO_ID = "hexgrad/Kokoro-82M"
_CONFIG_FILE = "config.json"
_WEIGHTS_FILE = "kokoro-v1_0.pth"
_MISSING_PACKAGE = "the 'kokoro' package is not installed; install ai-tts with the [kokoro] extra"

# Kokoro v1.0 voices (hexgrad/Kokoro-82M). Every voice listed here was
# verified to synthesize with the dependencies this project installs: the
# English sets use misaki[en], and Spanish, French, Hindi, Italian and
# Portuguese go through misaki's espeak backend.
#
# The Japanese (jf_/jm_) and Mandarin (zf_/zm_) voices ship in the same model
# repository and are deliberately absent: they need misaki[ja] (pyopenjtalk,
# which builds from source and bundles Open JTalk) and misaki[zh]. Adding
# either is a supply-chain decision, not a voice-list edit.
#
# The daemon enumerates these; clients and UIs must never hardcode a voice.
VOICES: tuple[str, ...] = (
    # American English
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
    # British English
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    # Spanish
    "ef_dora",
    "em_alex",
    "em_santa",
    # French
    "ff_siwis",
    # Hindi
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    # Italian
    "if_sara",
    "im_nicola",
    # Brazilian Portuguese
    "pf_dora",
    "pm_alex",
    "pm_santa",
)


class ModelAssetError(SynthesisError):
    """Raised when a model file is neither cached nor retrievable."""


class ModelAssetDownloadPort(Protocol):
    """Resolve one file of a model repository to a local path."""

    def __call__(self, *, repo_id: str, filename: str, local_files_only: bool) -> str:
        """Return the local path, raising when it cannot be resolved."""
        ...


def _hf_hub_download(*, repo_id: str, filename: str, local_files_only: bool) -> str:
    from huggingface_hub import hf_hub_download  # noqa: PLC0415 - keep off import time

    resolved: str = hf_hub_download(
        repo_id=repo_id, filename=filename, local_files_only=local_files_only
    )
    return resolved


class KokoroAssets:
    """Resolve model files from the local cache first, fetching only what is absent.

    Resolutions are remembered, so a long-lived daemon asks once per file
    rather than once per clip.
    """

    def __init__(
        self,
        *,
        repo_id: str = _DEFAULT_REPO_ID,
        download: ModelAssetDownloadPort = _hf_hub_download,
    ) -> None:
        """Resolve files of ``repo_id`` through ``download``."""
        self._repo_id = repo_id
        self._download = download
        self._resolved: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def repo_id(self) -> str:
        """The model repository these assets come from."""
        return self._repo_id

    def path(self, filename: str) -> str:
        """Return a local path for ``filename``, preferring the cache.

        Resolution happens outside the lock. A first run may have to fetch the
        file, and holding the lock across that would stall every synthesis
        worker behind one download. Two workers racing on the same file both
        resolve it, which is harmless — the answer is the same path — and the
        first one recorded wins.
        """
        with self._lock:
            cached = self._resolved.get(filename)
        if cached is not None:
            return cached
        resolved = self._resolve(filename)
        with self._lock:
            return self._resolved.setdefault(filename, resolved)

    def voice_path(self, voice: str) -> str:
        """Return a local path for one voice pack.

        The pipeline is handed this path rather than the voice id: given an id
        it re-resolves the pack through the model host on every load.
        """
        return self.path(f"voices/{voice}.pt")

    def _resolve(self, filename: str) -> str:
        try:
            return self._download(repo_id=self._repo_id, filename=filename, local_files_only=True)
        except Exception:  # noqa: BLE001 - any cache miss means we must fetch it
            log.info("event=model_asset_fetch_required")
        try:
            return self._download(repo_id=self._repo_id, filename=filename, local_files_only=False)
        except Exception as exc:
            # The transport error can carry a URL and proxy details; name the
            # asset instead and keep the cause off the message.
            msg = f"could not resolve model asset {filename!r} locally or remotely"
            raise ModelAssetError(msg) from exc


class KokoroEngine:
    """Speaks through the ``kokoro`` package's KPipeline."""

    name = "kokoro"
    is_local = True

    def __init__(self, *, assets: KokoroAssets | None = None) -> None:
        """Create the adapter; the model loads on warmup or first use."""
        self._pipelines: dict[str, Any] = {}
        self._model: Any = None
        self._assets = assets if assets is not None else KokoroAssets()
        self._lock = threading.Lock()

    def _shared_model(self) -> Any:  # noqa: ANN401 - kokoro ships no type stubs
        """One model, built from local paths, shared by every language pipeline."""
        if self._model is None:
            try:
                from kokoro import KModel  # noqa: PLC0415 - import on first use
            except ImportError as exc:  # pragma: no cover - install-time problem
                raise SynthesisError(_MISSING_PACKAGE) from exc
            self._model = KModel(
                repo_id=self._assets.repo_id,
                config=self._assets.path(_CONFIG_FILE),
                model=self._assets.path(_WEIGHTS_FILE),
            )
        return self._model

    def _pipeline(self, voice: str) -> Any:  # noqa: ANN401 - kokoro ships no type stubs
        lang_code = voice[0]
        with self._lock:
            pipeline = self._pipelines.get(lang_code)
            if pipeline is None:
                try:
                    from kokoro import KPipeline  # noqa: PLC0415 - import on first use
                except ImportError as exc:  # pragma: no cover - install-time problem
                    raise SynthesisError(_MISSING_PACKAGE) from exc
                pipeline = KPipeline(
                    lang_code=lang_code,
                    repo_id=self._assets.repo_id,
                    model=self._shared_model(),
                )
                self._pipelines[lang_code] = pipeline
        return pipeline

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Render ``text`` to a WAV at ``out_path``; return its duration in ms."""
        import numpy as np  # noqa: PLC0415 - keep numpy out of module import time
        import soundfile as sf  # noqa: PLC0415

        pipeline = self._pipeline(voice)
        # A path, not the id: the id would be resolved through the model host.
        voice_pack = self._assets.voice_path(voice)
        chunks: list[Any] = []
        try:
            for result in pipeline(text, voice=voice_pack, speed=speed):
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
