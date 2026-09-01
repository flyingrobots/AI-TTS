# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures: a temp store, a fake engine, and a fake audio sink."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from aitts.store import Store

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    st = Store(tmp_path / "state.db")
    yield st
    st.close()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine(voices=["bm_daniel", "af_bella"])


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


async def wait_for(predicate: object, timeout: float = 5.0) -> None:
    """Poll a zero-arg callable until it returns truthy or the timeout expires."""
    assert callable(predicate)
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            msg = "condition not met before timeout"
            raise AssertionError(msg)
        await asyncio.sleep(0.005)
