# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Packaged playback cues, separate from speech and its source clock."""

from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf


def cue_path(name: str) -> Path:
    """Locate a bundled cue independently of the working directory."""
    packaged = Path(__file__).parent / "assets" / name
    return packaged if packaged.is_file() else Path(__file__).parents[2] / "assets" / name


@cache
def earcon_pcm() -> bytes:
    """Decode the ascending intro to the sink's 24 kHz mono PCM16 format."""
    samples, rate = sf.read(str(cue_path("chime_intro_ascending.wav")), dtype="int16")
    frames = round(len(samples) * 24000 / rate)
    converted = np.interp(np.arange(frames) * rate / 24000, np.arange(len(samples)), samples)
    return bytes(converted.round().astype("<i2").tobytes())


def cue_padding_pcm() -> bytes:
    """Return 150 ms of silence at the cue's fixed 24 kHz PCM16 rate."""
    return bytes(3600 * 2)
