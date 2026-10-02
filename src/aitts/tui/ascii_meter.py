# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A bounded dBFS bar driven exclusively by measured output samples."""

import math


def format_meter(peak: float | None, width: int = 20) -> str:
    """Map zero to silence, unity to full scale, and absent telemetry to unknown."""
    if peak is None or not math.isfinite(peak):
        return "Audio level unavailable"
    peak = min(1.0, max(0.0, peak))
    decibels = max(-60.0, 20 * math.log10(peak)) if peak else -60.0
    filled = round((decibels + 60) / 60 * width)
    label = f"{decibels:.0f}" if peak else "-inf"
    return f"Output [{'█' * filled}{'·' * (width - filled)}] {label} dBFS"
