# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Python reference command for external socket tests; no model or audio device is used."""

import asyncio
import os
import signal
from pathlib import Path

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink


async def serve() -> None:
    """Serve the real Python protocol with deterministic owned synthesis and playback ports."""
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    daemon = Daemon(
        home=Path(os.environ["AI_TTS_HOME"]),
        socket_path=Path(os.environ["AI_TTS_SOCKET"]),
        engine=FakeEngine(voices=["bm_daniel", "af_bella"]),
        sink=FakeSink(auto_finish_ms=5),
        workers=2,
        input_activity=FakeInputActivity(),
    )
    await daemon.start()
    try:
        await stopped.wait()
    finally:
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(serve())
