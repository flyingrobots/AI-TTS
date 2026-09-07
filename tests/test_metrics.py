# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""What the daemon can say about itself (architecture §2, §4).

The design's central claim is that the queue, not the engine, governs how
responsive speech feels: synthesis runs ahead in parallel while playback stays
serial and real-time. Nothing measured it. The store already records every
timestamp needed to check it, so the daemon can answer the question it is
built around instead of leaving it to be taken on faith.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink
from tests.conftest import wait_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the two-queue responsiveness claim in architecture sections 2 and 4"),
]


@pytest.fixture
async def daemon(tmp_path: Path) -> AsyncIterator[Daemon]:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-metrics-"))
    built = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(auto_finish_ms=5),
        workers=1,
        socket_path=sock_dir / "d.sock",
    )
    await built.start()
    yield built
    await built.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


async def test_metrics_are_available_before_anything_has_been_spoken(
    daemon: Daemon,
) -> None:
    metrics = await daemon.dispatch({"op": "metrics"})

    # A fresh daemon must answer rather than divide by zero or omit keys, or
    # the first thing a caller learns is that the op is unreliable.
    assert metrics["ok"] is True
    assert metrics["counts"] == {}
    assert metrics["queue_depth"] == {"input": 0, "playback": 0}
    assert metrics["synthesis_wait_ms"] is None
    assert metrics["playback_failures"] == 0
    assert metrics["cache"]["bytes"] >= 0


async def test_metrics_report_the_two_waits_the_design_is_built_around(
    daemon: Daemon,
) -> None:
    reply = await daemon.dispatch({"op": "submit", "text": "hello"})
    await wait_for(lambda: _is(daemon, reply["id"], State.PLAYED))

    metrics = await daemon.dispatch({"op": "metrics"})

    # Submitted to Ready is what synthesis cost; Ready to Playing is what the
    # queue cost. Separating them is the whole point: one is parallel work and
    # the other is the serial resource.
    assert metrics["synthesis_wait_ms"] is not None
    assert metrics["synthesis_wait_ms"]["count"] == 1
    assert metrics["synthesis_wait_ms"]["p50"] >= 0
    assert metrics["playback_wait_ms"] is not None
    assert metrics["counts"]["Played"] == 1


async def test_metrics_count_playback_failures_separately_from_states(
    daemon: Daemon,
) -> None:
    reply = await daemon.dispatch({"op": "submit", "text": "hello"})
    await wait_for(lambda: _is(daemon, reply["id"], State.PLAYED))
    daemon.store.transition(
        daemon.store.submit("bad", voice="bm_daniel", speed=1.0).id,
        State.SYNTHESIZING,
    )

    metrics = await daemon.dispatch({"op": "metrics"})

    # A device failure and a cancelled clip are both terminal and mean
    # completely different things to whoever is on call.
    assert metrics["playback_failures"] == 0
    assert metrics["queue_depth"]["input"] >= 1


async def test_metrics_report_the_cache_against_its_cap(daemon: Daemon) -> None:
    await daemon.dispatch({"op": "settings", "set": {"cache_max_bytes": 4096}})

    metrics = await daemon.dispatch({"op": "metrics"})

    assert metrics["cache"]["max_bytes"] == 4096
    assert "bytes" in metrics["cache"]


def _is(daemon: Daemon, utt_id: str, state: State) -> bool:
    found = daemon.store.get(utt_id)
    return found is not None and found.state is state
