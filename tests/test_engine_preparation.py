# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A first run must not look like a hang.

The engine's weights are around 330 MB and are fetched on first use. Until
they arrive nothing can be spoken, and the daemon reported exactly what it
reports for a fast clip: the utterance sits in Synthesizing. An operator
watching a fresh install had no way to tell a download from a wedge, which is
the difference between waiting and restarting the daemon.

Two things make it legible. The engine says which asset it is fetching and
since when, and that report reaches the same snapshot everything else is read
from. When a fetch fails, the message says which asset and what a first run
needs, without pasting a transport error that can carry a URL or proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aitts.engines.kokoro import KokoroAssets, KokoroEngine, ModelAssetError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the first-run experience described in README's installation section"),
]

REPO = "hexgrad/Kokoro-82M"


class BlockingHub:
    """A model host whose fetch can be inspected while it is in flight."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.observed: list[object] = []
        # Read mid-fetch: the only moment the report has to be right.
        self.probe: Callable[[], object] = lambda: None

    def download(self, *, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id
        if local_files_only:
            msg = f"{filename} is not cached"
            raise FileNotFoundError(msg)
        self.observed.append(self.probe())
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset")
        return str(path)


def test_a_fetch_in_flight_names_the_asset_being_fetched(tmp_path: Path) -> None:
    hub = BlockingHub(tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)
    hub.probe = lambda: assets.fetching

    assets.path("kokoro-v1_0.pth")

    # "Downloading the weights" and "stuck" look identical without this.
    assert hub.observed == [("kokoro-v1_0.pth", hub.observed[0][1])]  # type: ignore[index]
    assert hub.observed[0][1] > 0  # type: ignore[index]


def test_nothing_is_reported_before_or_after_a_fetch(tmp_path: Path) -> None:
    hub = BlockingHub(tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)
    hub.probe = lambda: assets.fetching

    assert assets.fetching is None
    assets.path("config.json")

    # A report that outlives its fetch would make a ready daemon look busy
    # forever, which is worse than saying nothing.
    assert assets.fetching is None


def test_a_cached_asset_reports_no_fetch_at_all(tmp_path: Path) -> None:
    calls: list[bool] = []

    def cached(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id
        calls.append(local_files_only)
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset")
        return str(path)

    assets = KokoroAssets(repo_id=REPO, download=cached)
    assets.path("config.json")

    assert calls == [True]
    assert assets.fetching is None


def test_a_failed_fetch_clears_the_report(tmp_path: Path) -> None:
    del tmp_path

    def absent_then_unreachable(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id
        if local_files_only:
            raise FileNotFoundError(2, "not cached")
        msg = f"no route to host for {filename}"
        raise OSError(msg)

    assets = KokoroAssets(repo_id=REPO, download=absent_then_unreachable)

    with pytest.raises(ModelAssetError):
        assets.path("config.json")

    # A fetch that failed is not a fetch still running: a report that outlived
    # its fetch would make a broken daemon look busy indefinitely.
    assert assets.fetching is None


def test_the_engine_passes_the_report_through(tmp_path: Path) -> None:
    hub = BlockingHub(tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)
    engine = KokoroEngine(assets=assets)
    hub.probe = engine.preparation

    assert engine.preparation() is None
    assets.path("kokoro-v1_0.pth")

    # The snapshot reads the engine, not its private asset resolver, so the
    # report has to survive the trip through the adapter boundary.
    assert hub.observed == [("kokoro-v1_0.pth", hub.observed[0][1])]  # type: ignore[index]
    assert engine.preparation() is None


# -- what the message has to say ------------------------------------------


def test_an_unfetchable_asset_says_what_a_first_run_needs() -> None:
    def absent_then_unreachable(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id
        if local_files_only:
            # Genuinely absent, which is the one local outcome that justifies
            # going out; the fetch is what then fails.
            raise FileNotFoundError(2, "not cached")
        msg = f"no route to host for {filename} via http://proxy.internal:3128"
        raise OSError(msg)

    assets = KokoroAssets(repo_id=REPO, download=absent_then_unreachable)

    with pytest.raises(ModelAssetError) as raised:
        assets.path("kokoro-v1_0.pth")

    message = str(raised.value)
    # Which asset, which repository, and the one thing the operator can act
    # on. The transport error stays out: it can carry a URL and proxy details.
    assert "kokoro-v1_0.pth" in message
    assert REPO in message
    assert "network" in message
    assert "proxy.internal" not in message


def test_an_unreadable_cache_says_it_is_a_local_problem() -> None:
    def guarded(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        raise PermissionError(13, f"Permission denied reading /private/cache/{filename}")

    assets = KokoroAssets(repo_id=REPO, download=guarded)

    with pytest.raises(ModelAssetError) as raised:
        assets.path("config.json")

    message = str(raised.value)
    # The two failures need different actions: this one is not fixed by
    # connecting to a network, and saying so is the whole diagnostic value.
    assert "config.json" in message
    assert "cache" in message
    assert "network" not in message
    assert "/private/cache" not in message
