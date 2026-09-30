# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""One daemon owns a state directory, independently of its socket path."""

import tempfile
from pathlib import Path

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("one daemon owns durable queues and playback for a state directory"),
]


async def test_second_daemon_cannot_share_state_through_another_socket(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="aitts-state-owner-") as sockets:
        first = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=FakeSink(),
            socket_path=Path(sockets) / "first.sock",
            input_activity=FakeInputActivity(),
        )
        second = Daemon(
            home=tmp_path,
            engine=FakeEngine(["v"]),
            sink=FakeSink(),
            socket_path=Path(sockets) / "second.sock",
            input_activity=FakeInputActivity(),
        )
        await first.start()
        try:
            with pytest.raises(RuntimeError, match="already owned"):
                await second.start()
            await second.stop()
            assert (await first.dispatch({"op": "status"}))["state"] == "accepting"
        finally:
            await second.stop()
            await first.stop()


async def test_failed_endpoint_start_releases_state_for_a_successor(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="aitts-start-failure-") as sockets:
        occupied = Path(sockets) / "occupied.sock"
        incumbent = Daemon(
            home=tmp_path / "incumbent",
            engine=FakeEngine(["v"]),
            sink=FakeSink(),
            socket_path=occupied,
            input_activity=FakeInputActivity(),
        )
        failed = Daemon(
            home=tmp_path / "candidate",
            engine=FakeEngine(["v"]),
            sink=FakeSink(),
            socket_path=occupied,
            input_activity=FakeInputActivity(),
        )
        await incumbent.start()
        try:
            with pytest.raises(RuntimeError, match="already owned"):
                await failed.start()
            successor = Daemon(
                home=tmp_path / "candidate",
                engine=FakeEngine(["v"]),
                sink=FakeSink(),
                socket_path=Path(sockets) / "successor.sock",
                input_activity=FakeInputActivity(),
            )
            try:
                await successor.start()
                assert (await successor.dispatch({"op": "status"}))["state"] == "accepting"
            finally:
                await successor.stop()
        finally:
            await failed.stop()
            await incumbent.stop()
