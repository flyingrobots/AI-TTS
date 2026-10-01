# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import test_native_ui_live as live

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the owned candidate is reaped before the incumbent app is restored"),
]


async def test_stubborn_candidate_is_reaped_before_incumbent_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Retire with the live session harness, or equivalent process-ownership coverage.
    spawn = asyncio.create_subprocess_exec
    children: list[asyncio.subprocess.Process] = []
    restored: list[bool] = []

    async def owned_spawn(*arguments: str, **kwargs: Any) -> asyncio.subprocess.Process:
        code = "import time; time.sleep(60)"
        if arguments[0].endswith("AITTSMenuBar"):
            code = (
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)"
            )
        kwargs["stdout"] = asyncio.subprocess.PIPE
        child = await spawn(sys.executable, "-c", code, **kwargs)
        children.append(child)
        return child

    async def incumbent(_probe: Path) -> tuple[int, Path]:
        return 123, tmp_path / "incumbent.app"

    async def stop(_pid: int) -> None:
        pass

    async def restore(*_arguments: str) -> str:
        restored.append(children[-1].returncode is not None)
        return ""

    monkeypatch.setattr(asyncio, "create_subprocess_exec", owned_spawn)
    monkeypatch.setattr(live, "incumbent_app", incumbent)
    monkeypatch.setattr(live, "stop_incumbent", stop)
    monkeypatch.setattr(live, "command", restore)
    try:
        try:
            async with live.candidate_session(tmp_path, tmp_path, tmp_path / "socket"):
                async with asyncio.timeout(3):
                    output = children[-1].stdout
                    if output is None or await output.readline() != b"ready\n":
                        pytest.fail("Owned candidate did not establish its signal handler")
        except TimeoutError:
            pass  # Inspect restoration even when the unfixed teardown times out.
        assert restored == [True], "restoration must follow candidate exit and reap"
    finally:
        for child in children:
            if child.returncode is None:
                child.kill()
            await child.wait()
