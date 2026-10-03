# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Prepared output ownership at the injected native device boundary."""

import threading
from typing import Any

import numpy as np
import pytest

from aitts.adapters.callback_output import PreparedCallbackOutput
from aitts.application.audio_device import FakeAudioDevice
from tests.test_streaming_pipeline import ManualCallbackDevice

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "one prepared device, silent idle output, explicit session and device completion"
    ),
]


def test_successive_sessions_reuse_output_and_leave_idle_silence() -> None:
    device = ManualCallbackDevice()
    route = FakeAudioDevice()
    prepared = PreparedCallbackOutput(route, device.open)
    finished = threading.Event()

    def render(output: Any, frames: int, underflow: bool) -> bool:  # noqa: FBT001 - native callback
        del frames, underflow
        output.fill(0.25)
        return False

    try:
        prepared.prepare()
        idle, running = device.block()
        assert running
        assert np.all(idle == 0)
        for _ in range(2):
            finished.clear()
            with prepared.session(
                samplerate=24000, channels=1, render=render, finished=finished.set
            ):
                block, running = device.block()
                assert running
                assert np.all(block == 0.25)
                assert finished.is_set()
            idle, running = device.block()
            assert running
            assert np.all(idle == 0)
        assert route.refreshes == 1
        route.identity = "new-output"
        with device.driving():
            prepared.prepare()
        assert route.refreshes == 2
    finally:
        with device.driving():
            prepared.close()
        with device.driving():
            prepared.close()


def test_unexpected_device_end_fails_session_and_next_prepare_reopens() -> None:
    device = ManualCallbackDevice()
    route = FakeAudioDevice()
    prepared = PreparedCallbackOutput(route, device.open)
    finished = threading.Event()

    def render(output: Any, frames: int, underflow: bool) -> bool:  # noqa: FBT001 - native callback
        del frames, underflow
        output.fill(0)
        return True

    try:
        with pytest.raises(RuntimeError, match="stopped unexpectedly"):  # noqa: PT012, SIM117 - fail on context exit
            with prepared.session(
                samplerate=24000, channels=1, render=render, finished=finished.set
            ):
                device.finished()
                assert finished.wait(1)
        with device.driving():
            prepared.prepare()
        assert route.refreshes == 2
        idle, running = device.block()
        assert running
        assert np.all(idle == 0)
    finally:
        with device.driving():
            prepared.close()


def test_renderer_failure_releases_owner_and_outputs_silence() -> None:
    device = ManualCallbackDevice()
    prepared = PreparedCallbackOutput(FakeAudioDevice(), device.open)
    finished = threading.Event()

    def render(output: Any, frames: int, underflow: bool) -> bool:  # noqa: FBT001 - native callback
        del output, frames, underflow
        msg = "seeded renderer failure"
        raise ValueError(msg)

    try:
        with pytest.raises(RuntimeError, match="seeded renderer failure"):  # noqa: PT012, SIM117 - fail on session exit
            with prepared.session(
                samplerate=24000, channels=1, render=render, finished=finished.set
            ):
                output, running = device.block()
                assert running is False
                assert np.all(output == 0)
                assert finished.wait(1)
    finally:
        with device.driving():
            prepared.close()


def test_shutdown_prevents_late_output_preparation() -> None:
    from aitts.playback import SoundDeviceSink  # noqa: PLC0415 - native sink boundary

    device = ManualCallbackDevice()
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    sink.close_output()
    try:
        sink.prepare_output()
        assert not device.opened.is_set()
    finally:
        sink.close_output()
