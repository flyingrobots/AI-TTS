# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Process-level daemon lifecycle contracts under non-cooperative engine work."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("bounded launch-agent shutdown contract under SIGTERM"),
]

_BLOCKING_DAEMON = """
import sys
import time

import aitts.engine


class BlockingFakeEngine(aitts.engine.FakeEngine):
    def warmup(self):
        time.sleep(30)


aitts.engine.FakeEngine = BlockingFakeEngine

from aitts.cli import main

raise SystemExit(
    main(
        [
            "--socket",
            sys.argv[1],
            "daemon",
            "--home",
            sys.argv[2],
            "--engine",
            "fake",
        ]
    )
)
"""


def test_sigterm_exits_promptly_while_engine_thread_is_blocked(tmp_path: Path) -> None:
    """Oracle: shutdown completes after durable resources close, not after engine work."""
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-lifecycle-"))
    socket_path = socket_dir / "daemon.sock"
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _BLOCKING_DAEMON, str(socket_path), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    socket_ready = False
    exited_promptly = False
    try:
        startup_deadline = time.monotonic() + 5
        while time.monotonic() < startup_deadline:
            if socket_path.exists():
                socket_ready = True
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)

        if socket_ready:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=2)
                exited_promptly = True
            except subprocess.TimeoutExpired:
                pass
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        stdout, stderr = process.communicate(timeout=2)
        shutil.rmtree(socket_dir)

    assert {
        "socket_ready": socket_ready,
        "exited_promptly": exited_promptly,
        "returncode": process.returncode,
    } == {
        "socket_ready": True,
        "exited_promptly": True,
        "returncode": 0,
    }, f"daemon stdout:\n{stdout}\ndaemon stderr:\n{stderr}"


def test_sigterm_exits_promptly_with_connected_subscriber(tmp_path: Path) -> None:
    """Oracle: an open JSONL subscription cannot retain the daemon process."""
    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-subscriber-lifecycle-"))
    socket_path = socket_dir / "daemon.sock"
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _BLOCKING_DAEMON, str(socket_path), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    subscriber = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_ready = False
    subscribed = False
    exited_promptly = False
    try:
        startup_deadline = time.monotonic() + 5
        while time.monotonic() < startup_deadline:
            if socket_path.exists():
                socket_ready = True
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)

        if socket_ready:
            subscriber.settimeout(1)
            subscriber.connect(str(socket_path))
            subscriber.sendall(b'{"op":"subscribe"}\n')
            receipt = json.loads(subscriber.recv(4096))
            subscribed = receipt == {"ok": True, "subscribed": True}
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=2)
                exited_promptly = True
            except subprocess.TimeoutExpired:
                pass
    finally:
        subscriber.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        stdout, stderr = process.communicate(timeout=2)
        shutil.rmtree(socket_dir)

    assert {
        "socket_ready": socket_ready,
        "subscribed": subscribed,
        "exited_promptly": exited_promptly,
        "returncode": process.returncode,
    } == {
        "socket_ready": True,
        "subscribed": True,
        "exited_promptly": True,
        "returncode": 0,
    }, f"daemon stdout:\n{stdout}\ndaemon stderr:\n{stderr}"
