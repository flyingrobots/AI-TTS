# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Maintenance admission and provenance through owned daemon operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.ipc import ApiError
from aitts.model import State
from aitts.playback import FakeSink

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("rejected maintenance requests preserve the previous retention policy"),
]


@pytest.fixture
async def idle_daemon(tmp_path: Path) -> AsyncIterator[Daemon]:
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(["v"]),
        sink=FakeSink(),
        input_activity=FakeInputActivity(active=False),
    )
    try:
        yield daemon
    finally:
        await daemon.stop()


@pytest.mark.parametrize("invalid_delete", ["not-a-list", ["clip", 1]])
async def test_rejected_storage_request_cannot_enable_retention(
    idle_daemon: Daemon, invalid_delete: object
) -> None:
    before = await idle_daemon.dispatch({"op": "storage"})
    with pytest.raises(ApiError, match="delete must contain artifact ids"):
        await idle_daemon.dispatch({"op": "storage", "retention_days": 1, "delete": invalid_delete})
    after = await idle_daemon.dispatch({"op": "storage"})
    assert after == before


@pytest.mark.parametrize(
    "source",
    ["menubar-file", "macos-accessibility", "macos-clipboard", "macos-service", "macos-intent"],
)
@pytest.mark.oracle("a History replay reports its own origin and retains the original caller")
async def test_replay_origin_is_not_overwritten_by_the_original_native_entry_point(
    idle_daemon: Daemon, source: str
) -> None:
    original = idle_daemon.store.submit("source", voice="v", speed=1.0, source=source)
    idle_daemon.store.transition(original.id, State.CANCELLED)
    replay = await idle_daemon.dispatch({"op": "requeue", "id": original.id})
    response = await idle_daemon.dispatch({"op": "provenance", "id": replay["id"]})
    provenance = response["provenance"]
    assert {key: provenance[key] for key in ("origin", "caller_source", "replay_of")} == {
        "origin": "History replay",
        "caller_source": source,
        "replay_of": original.id,
    }
