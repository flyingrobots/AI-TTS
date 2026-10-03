# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Issue #94: native completion, not a stop request, permits device reuse."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from aitts.adapters import callback_output
from aitts.adapters.callback_output import PreparedCallbackOutput
from aitts.application.audio_device import FakeAudioDevice
from aitts.playback import SoundDeviceSink
from tests.test_streaming_pipeline import ManualCallbackDevice

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "#94 / PortAudio: only native finished permits stream cleanup and replacement"
    ),
]


class HeldCompletionDevice(ManualCallbackDevice):
    """Own the native-finished boundary independently of renderer completion."""

    def __init__(self) -> None:
        super().__init__()
        self.confirmed = False
        self.exits: list[bool] = []

    @contextlib.contextmanager
    def open(self, **kwargs: Any) -> Iterator[object]:
        with super().open(**kwargs) as stream:
            try:
                yield stream
            finally:
                self.exits.append(self.confirmed)

    def confirm(self) -> None:
        self.confirmed = True
        self.finished()


@pytest.fixture(autouse=True)
def close_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Own the native timeout; the oracle is refusal, not elapsed wall time.
    monkeypatch.setattr(callback_output, "CLOSE_TIMEOUT_SECONDS", 0.05, raising=False)


@pytest.mark.parametrize("renderer_fails", [False, True])
def test_unconfirmed_native_completion_refuses_cleanup(*, renderer_fails: bool) -> None:
    device = HeldCompletionDevice()
    prepared = PreparedCallbackOutput(FakeAudioDevice(), device.open)

    def render(output: Any, frames: int, underflow: bool) -> bool:  # noqa: FBT001 - callback contract
        del output, frames, underflow
        msg = "owned renderer failure"
        raise ValueError(msg)

    prepared.prepare()
    try:
        if renderer_fails:
            with pytest.raises(RuntimeError, match="owned renderer failure"):  # noqa: PT012, SIM117 - error on session exit
                with prepared.session(
                    samplerate=24000, channels=1, render=render, finished=lambda: None
                ):
                    block = np.ones((240, 1), dtype=np.float32)
                    assert device.render(block, 240, False) is False  # noqa: FBT003 - native callback
                    assert not block.any()
        with pytest.raises(RuntimeError, match="did not close"):
            prepared.close()
        # A timed-out stop must not masquerade as a reusable prepared device.
        with pytest.raises(RuntimeError, match="did not close"):
            prepared.prepare()
        assert device.exits == []
    finally:
        device.confirm()
        prepared.close()
    assert device.exits == [True]
    prepared.close()


async def test_float_wav_cannot_replace_unconfirmed_prepared_output(tmp_path: Path) -> None:
    device = HeldCompletionDevice()
    writes: list[int] = []

    class FileOutput:
        def write(self, block: Any) -> bool:
            writes.append(len(block))
            return False

    @contextlib.contextmanager
    def file_output(**kwargs: Any) -> Iterator[FileOutput]:
        del kwargs
        assert device.exits == [True], "file playback overlapped the native callback owner"
        yield FileOutput()

    path = tmp_path / "chatterbox-format.wav"
    sf.write(path, np.full(2400, 0.25), 24000, subtype="FLOAT")
    sink = SoundDeviceSink(
        device=FakeAudioDevice(), open_callback_stream=device.open, open_stream=file_output
    )
    sink.prepare_output()
    try:
        sink.start(path)
        assert await asyncio.wait_for(sink.wait(), 2) is False
        assert sink.error == "audio callback device did not close"
        assert writes == []
        device.confirm()
        sink.start(path)
        assert await asyncio.wait_for(sink.wait(), 2) is True
        assert sum(writes) >= 2400
    finally:
        device.confirm()
        await asyncio.to_thread(sink.close_output)


def test_failed_native_preparation_can_be_retried_without_a_live_owner() -> None:
    device = HeldCompletionDevice()
    attempts = 0

    @contextlib.contextmanager
    def factory(**kwargs: Any) -> Iterator[object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            msg = "owned open failure"
            raise OSError(msg)
        with device.open(**kwargs) as stream:
            yield stream

    prepared = PreparedCallbackOutput(FakeAudioDevice(), factory)
    with pytest.raises(RuntimeError, match="owned open failure"):
        prepared.prepare()
    try:
        prepared.prepare()
        assert attempts == 2
        assert device.opened.is_set()
    finally:
        device.confirm()
        prepared.close()
    assert device.exits == [True]
