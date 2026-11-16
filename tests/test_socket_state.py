# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""State monitoring tolerates owned cleanup and refuses unobservable or excessive state."""

from __future__ import annotations

import errno
import os
import signal
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests import socket_daemon
from tests.socket_daemon import DaemonProcessError, daemon_process

pytestmark = [pytest.mark.medium, pytest.mark.oracle("issue #114 bounded state monitoring")]


async def test_disappearing_descendant_does_not_kill_a_healthy_daemon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappearing = tmp_path / "temporary"
    disappearing.mkdir()
    process = SimpleNamespace(pid=42, returncode=None)
    signals: list[int] = []
    failures: list[str] = []
    scan, walk = os.scandir, os.walk

    def remove_before_scan(path: Any) -> Any:
        if Path(path) == disappearing:
            disappearing.rmdir()
        return scan(path)

    def one_scan(*args: Any, **kwargs: Any) -> Iterator[tuple[str, list[str], list[str]]]:
        yield from walk(*args, **kwargs)
        process.returncode = 0

    monkeypatch.setattr(os, "scandir", remove_before_scan)
    monkeypatch.setattr(os, "walk", one_scan)
    monkeypatch.setattr(socket_daemon, "_signal_group", lambda _process, sig: signals.append(sig))
    await socket_daemon._watch_state(cast("Any", process), tmp_path, failures)
    assert {"signals": signals, "failures": failures, "remaining": disappearing.exists()} == {
        "signals": [],
        "failures": [],
        "remaining": False,
    }


@pytest.mark.parametrize(
    "failure",
    ["missing-root", "missing-ancestor", "denied-descendant", "unknown-missing"],
)
async def test_unconfirmed_state_scan_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    process = SimpleNamespace(pid=42, returncode=None)
    signals: list[int] = []
    failures: list[str] = []
    errors = {
        "missing-root": FileNotFoundError(errno.ENOENT, "gone", str(tmp_path)),
        "missing-ancestor": FileNotFoundError(errno.ENOENT, "gone", str(tmp_path / "child")),
        "denied-descendant": PermissionError(errno.EACCES, "denied", str(tmp_path / "child")),
        "unknown-missing": FileNotFoundError(errno.ENOENT, "unknown path"),
    }

    def failed_scan(*_args: Any, **kwargs: Any) -> list[object]:
        if failure == "missing-ancestor":
            tmp_path.rmdir()
        kwargs["onerror"](errors[failure])
        process.returncode = 0
        return []

    monkeypatch.setattr(os, "walk", failed_scan)
    monkeypatch.setattr(socket_daemon, "_signal_group", lambda _process, sig: signals.append(sig))
    await socket_daemon._watch_state(cast("Any", process), tmp_path, failures)
    assert signals == [signal.SIGKILL]
    assert len(failures) == 1
    assert failures[0].startswith("daemon state monitor failed:")


async def test_empty_directories_exhaust_the_state_entry_budget(tmp_path: Path) -> None:
    script = (
        "import os,pathlib,time\n"
        "home=pathlib.Path(os.environ['AI_TTS_HOME'])\n"
        "for i in range(4100): (home/str(i)).mkdir()\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(DaemonProcessError, match="state directory limit"):
        async with daemon_process(tmp_path, command=[sys.executable, "-c", script]):
            pytest.fail("directory-only growth escaped the state budget")
    assert not list(tmp_path.iterdir())
