# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Model reload ownership survives cancellation of its requesting task."""

from __future__ import annotations

import asyncio
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from aitts.synthesis import SynthesisPool
from tests.test_ipc import wait_for_async

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "model reload owns synthesis exclusion and readiness until restart finishes"
    ),
]


@pytest.mark.parametrize("fails", [False, True])
async def test_cancelled_reload_request_still_publishes_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fails: bool
) -> None:
    # Retire if model reload disappears or another lifecycle contract subsumes it.
    pools: list[SynthesisPool] = []

    class ObservedPool(SynthesisPool):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            pools.append(self)

    # Capture the real synthesis port at composition; do not reach into Daemon.
    monkeypatch.setattr("aitts.daemon.SynthesisPool", ObservedPool)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class ReloadEngine(FakeEngine):
        def restart(self) -> None:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                message = "test did not release model restart"
                raise TimeoutError(message)
            if fails:
                message = "controlled restart failure"
                raise RuntimeError(message)

    with tempfile.TemporaryDirectory(prefix="aitts-reload-") as sockets:
        daemon = Daemon(
            home=tmp_path,
            engine=ReloadEngine(["v"]),
            sink=FakeSink(),
            socket_path=Path(sockets) / "d.sock",
            input_activity=FakeInputActivity(),
        )
        await daemon.start()
        request: asyncio.Task[dict[str, object]] | None = None
        try:

            async def ready() -> bool:
                snapshot = await daemon.dispatch({"op": "snapshot"})
                return bool(snapshot["runtime"]["model_state"] == "ready")

            await wait_for_async(ready)
            request = asyncio.create_task(daemon.dispatch({"op": "restart_model"}))
            await asyncio.wait_for(entered.wait(), 2)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert not pools[0].enabled.is_set()
            release.set()

            async def completed() -> bool:
                state = (await daemon.dispatch({"op": "snapshot"}))["runtime"]["model_state"]
                return bool(state == ("failed" if fails else "ready"))

            await wait_for_async(completed)
        finally:
            release.set()
            if request is not None:
                await asyncio.gather(request, return_exceptions=True)
            await daemon.stop()
