# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Issue #94: a native input read cannot own daemon liveness."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from tests.test_ipc import rpc

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "#94: status and shutdown remain available while a native input read is held"
    ),
]


async def test_held_input_read_does_not_block_status_or_shutdown(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    finished_test = threading.Event()
    calls: list[int] = []

    class HeldInput:
        def input_is_active(self) -> bool:
            calls.append(threading.get_ident())
            entered.set()
            try:
                release.wait()
                return True
            finally:
                returned.set()

    # Unfixed code blocks the event loop, including asyncio timeouts. An owned
    # watchdog releases only the test's native read so RED is an assertion.
    def watchdog() -> None:
        if not finished_test.wait(1):
            release.set()

    guard = threading.Thread(target=watchdog)
    guard.start()
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-held-"))
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(),
        socket_path=socket_dir / "s",
        input_activity=HeldInput(),
        input_poll_seconds=0.001,
    )
    await daemon.start()
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        response = await rpc(daemon.socket_path, {"op": "status"})
        assert response["ok"] is True
        assert not release.is_set(), "status waited for the blocked native input read"
        await daemon.stop()
        assert not release.is_set(), "shutdown waited for the blocked native input read"
        assert len(calls) == 1
    finally:
        finished_test.set()
        release.set()
        await daemon.stop()
        guard.join(2)
        assert returned.wait(1)
        shutil.rmtree(socket_dir)


def test_process_exits_with_a_native_input_read_still_blocked() -> None:
    """The real asyncio runner must not join an abandoned native probe at exit."""
    import subprocess  # noqa: PLC0415 - subprocess is this test's boundary
    import sys  # noqa: PLC0415

    program = """
import asyncio
import threading
from aitts.input_interrupt import InputInterruptWatcher

entered = threading.Event()
class Blocked:
    def input_is_active(self):
        entered.set()
        threading.Event().wait()

async def main():
    watcher = InputInterruptWatcher(
        Blocked(), None, controller=lambda: None, announce=lambda _: None
    )
    task = asyncio.create_task(watcher.run())
    while not entered.is_set():
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

asyncio.run(main())
print("runner exited with native read blocked", flush=True)
"""
    # A fresh process isolates interpreter/default-executor shutdown from pytest.
    result = subprocess.run(  # noqa: S603 - owned interpreter and program
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "runner exited with native read blocked"
