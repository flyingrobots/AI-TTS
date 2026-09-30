# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Explicit composer model choices cannot silently select another backend."""

import pytest

from aitts.daemon import Daemon
from tests.test_ipc import daemon as daemon_fixture
from tests.test_ipc import rpc

daemon = daemon_fixture

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("explicit model identity is enforced before accepting source text"),
]


async def test_composer_rejects_unavailable_model_without_admitting_clip(daemon: Daemon) -> None:
    before = daemon.store.counts()
    response = await rpc(
        daemon.socket_path, {"op": "submit", "text": "Draft", "engine": "unavailable-model"}
    )
    assert response["ok"] is False
    assert "model" in response["error"]["message"]
    assert daemon.store.counts() == before


async def test_composer_accepts_running_model_and_selected_voice(daemon: Daemon) -> None:
    response = await rpc(
        daemon.socket_path,
        {"op": "submit", "text": "Draft", "engine": "fake", "voice": "af_bella"},
    )
    assert response["ok"] is True
    assert response["voice"] == "af_bella"
