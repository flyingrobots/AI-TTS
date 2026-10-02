# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Meter values come from actual output blocks, never synthesis activity."""

import asyncio
import struct
from pathlib import Path

import pytest

from aitts.application.audio_device import FakeAudioDevice
from aitts.playback import SoundDeviceSink
from aitts.streaming import SpoolingPCMStream
from aitts.tui.ascii_meter import format_meter
from tests.test_streaming_pipeline import ManualCallbackDevice


@pytest.mark.small
@pytest.mark.oracle("20 log10 amplitude: silence empty, -20 dBFS two thirds, unity full")
def test_meter_shows_measured_dbfs_and_distinguishes_unknown() -> None:
    assert format_meter(0, 6) == "Output [······] -inf dBFS"
    assert format_meter(0.1, 6) == "Output [████··] -20 dBFS"
    assert format_meter(1, 6) == "Output [██████] 0 dBFS"
    assert format_meter(None) == "Audio level unavailable"


@pytest.mark.medium
@pytest.mark.oracle("native output callback peak equals the known PCM block amplitude")
async def test_output_meter_measures_rendered_samples(tmp_path: Path) -> None:
    device = ManualCallbackDevice()
    source = SpoolingPCMStream(tmp_path / "meter.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    try:
        source.append(struct.pack("<480h", *([8192] * 480)))
        source.seal()
        source.finish()
        assert source.wait_buffered(480, timeout=1)
        sink.start_stream(source, artifact_id="owned-meter")
        assert await asyncio.to_thread(device.opened.wait, 1)
        output, _ = device.block()
        assert sink.audio_peak() == float(output.max()) == 0.25
        device.block()
        device.block()
        assert await asyncio.wait_for(sink.wait(), 1)
    finally:
        sink.stop()
        if device.opened.is_set():
            device.block()
        sink.close_output()
        source.close()
