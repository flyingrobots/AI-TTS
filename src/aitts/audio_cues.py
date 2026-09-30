# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Short playback cues, kept separate from generated speech and its evidence."""

from __future__ import annotations

import math
import struct
from functools import cache


@cache
def earcon_pcm() -> bytes:
    """Return a 100 ms, 880 Hz chime as 24 kHz mono little-endian PCM16.

    A sine-squared envelope begins and ends at silence; 12% peak amplitude keeps
    the cue gentle. Playback speed does not change its pitch or duration.
    """
    frames = 2400
    samples = [
        round(
            32767
            * 0.12
            * math.sin(math.pi * index / (frames - 1)) ** 2
            * math.sin(2 * math.pi * 880 * index / 24000)
        )
        for index in range(frames)
    ]
    return struct.pack(f"<{frames}h", *samples)
