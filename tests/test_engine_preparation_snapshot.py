# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The engine's readiness report has to reach the snapshot to be worth anything.

The report itself is checked in :mod:`tests.test_engine_preparation`, which is
small. These stand up a real daemon over a real socket, so they are medium:
what they establish is that a report the engine keeps to itself explains
nothing to the person watching a fresh install.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the first-run experience described in README's installation section"),
]


# -- the report has to reach the snapshot to be worth anything ------------


async def test_the_snapshot_says_the_engine_is_still_getting_ready(
    prepared_daemon: tuple[Daemon, FakeEngine],
) -> None:
    daemon, engine = prepared_daemon
    engine.preparing = ("kokoro-v1_0.pth", 1_700_000_000.0)

    status = await daemon.dispatch({"op": "status"})

    # The snapshot is the one thing every client reads. A report the engine
    # keeps to itself explains nothing to the person watching a fresh install.
    assert status["engine_preparing"] == {
        "asset": "kokoro-v1_0.pth",
        "since": 1_700_000_000.0,
    }


async def test_a_ready_engine_reports_no_preparation(
    prepared_daemon: tuple[Daemon, FakeEngine],
) -> None:
    daemon, _ = prepared_daemon

    status = await daemon.dispatch({"op": "status"})

    # Absent, not an empty object: "ready" and "preparing something unnamed"
    # must not read the same.
    assert status["engine_preparing"] is None


async def test_an_engine_that_cannot_report_is_not_an_error(tmp_path: Path) -> None:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-prep-"))
    plain = _PlainEngine()
    daemon = Daemon(
        home=tmp_path,
        engine=plain,
        sink=FakeSink(auto_finish_ms=5),
        workers=1,
        socket_path=sock_dir / "d.sock",
    )
    await daemon.start()
    try:
        status = await daemon.dispatch({"op": "status"})
    finally:
        await daemon.stop()
        shutil.rmtree(sock_dir, ignore_errors=True)

    # The engine boundary is a small protocol with one real implementation.
    # Reporting readiness is optional, and an engine that does not is ready.
    assert status["ok"] is True
    assert status["engine_preparing"] is None


class _PlainEngine(FakeEngine):
    """An engine with no readiness report at all."""

    def __init__(self) -> None:
        super().__init__(voices=["bm_daniel"])

    preparation = None  # type: ignore[assignment]


@pytest.fixture
async def prepared_daemon(tmp_path: Path) -> AsyncIterator[tuple[Daemon, FakeEngine]]:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-prep-"))
    engine = FakeEngine(voices=["bm_daniel"])
    daemon = Daemon(
        home=tmp_path,
        engine=engine,
        sink=FakeSink(auto_finish_ms=5),
        workers=1,
        socket_path=sock_dir / "d.sock",
    )
    await daemon.start()
    yield daemon, engine
    await daemon.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)
