# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Regenerate the Python ``submitted``/``audio_generated`` fixture for aitts-artifacts.

Run from the repository root: ``uv run python scripts/generate_evidence_writer_fixtures.py``.
``writers/audio/*.wav`` are inputs written by ``soundfile``. ``writers/root`` is the
evidence the Python ``ClipEvidence`` writers leave for them, with the wall clock
pinned at ``RECEIVED_AT``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from aitts.adapters.clip_evidence import ClipEvidence

FIXTURES = Path("crates/aitts-artifacts/tests/fixtures/writers")
RECEIVED_AT = 1_800_000_000.25
PAYLOAD = {
    "op": "speak",
    "text": "Hello, ünïcode world.",
    "voice": "af_heart",
    "speed": 1.1,
    "tags": ["agent", "ünï"],
}


def write_inputs(audio: Path) -> None:
    """Three formats: PCM_16 mono with clipping, PCM_24 mono, FLOAT stereo with NaN and inf."""
    audio.mkdir(parents=True)
    pcm16 = np.array([0, 1000, -1000, 32767, -32768, 32765, -32764, 12345], dtype=np.int16)
    sf.write(audio / "pcm16.wav", pcm16, 24000, subtype="PCM_16")
    pcm24 = np.array([0.0, 0.5, -0.25, 0.99995, -0.75], dtype=np.float64)
    sf.write(audio / "pcm24.wav", pcm24, 22050, subtype="PCM_24")
    stereo = np.array(
        [[0.1, -0.2], [np.nan, 0.75], [np.inf, -0.5], [1.0, -np.inf]], dtype=np.float32
    )
    sf.write(audio / "float.wav", stereo, 48000, subtype="FLOAT")


def main() -> None:
    """Write the inputs and the Python evidence for them."""
    shutil.rmtree(FIXTURES, ignore_errors=True)
    write_inputs(FIXTURES / "audio")
    with mock.patch("aitts.adapters.clip_evidence.time.time", return_value=RECEIVED_AT):
        evidence = ClipEvidence(FIXTURES / "root")
        evidence.submitted("clip-s", str(PAYLOAD["text"]), PAYLOAD)
        for name in ("pcm16", "pcm24", "float"):
            evidence.audio_generated(f"clip-{name}", FIXTURES / "audio" / f"{name}.wav")


if __name__ == "__main__":
    main()
