# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The engine reaches the network once, not on every clip (architecture §9).

The text this daemon speaks is client-confidential, and a local engine was
chosen so that it never leaves the machine. That guarantee has a hole if the
engine adapter asks a model host to resolve its weights and voice packs each
time it loads one: the request names the exact voice and the moment it spoke,
which is metadata about confidential speech leaving the machine, and it makes
the daemon useless offline.

Assets therefore resolve from the local cache first, and only a genuinely
absent file is fetched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aitts.engines.kokoro import KokoroAssets, ModelAssetError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "the local-first confidentiality posture in architecture section 9 and the "
        "locally resolved engine dependency promised in README"
    ),
]

REPO = "hexgrad/Kokoro-82M"


class RecordingHub:
    """A model host that records how each asset was asked for."""

    def __init__(self, *, cached: set[str] | None = None, root: Path | None = None) -> None:
        self.cached = cached if cached is not None else set()
        self.root = root
        self.calls: list[tuple[str, bool]] = []

    def download(self, *, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id
        self.calls.append((filename, local_files_only))
        if local_files_only and filename not in self.cached:
            # What the real model host raises for a local miss: its
            # LocalEntryNotFoundError subclasses FileNotFoundError.
            msg = f"{filename} is not cached"
            raise FileNotFoundError(msg)
        if self.root is None:  # pragma: no cover - tests that need a path pass one
            return f"/cache/{filename}"
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset")
        return str(path)

    @property
    def offline_only(self) -> bool:
        """Whether every resolution stayed offline."""
        return all(local_only for _, local_only in self.calls)


def test_a_cached_asset_never_reaches_the_network(tmp_path: Path) -> None:
    hub = RecordingHub(cached={"config.json"}, root=tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)

    assets.path("config.json")

    # One offline lookup, and no second attempt that would have gone out.
    assert hub.calls == [("config.json", True)]
    assert hub.offline_only is True


def test_an_absent_asset_is_fetched_once_then_stays_local(tmp_path: Path) -> None:
    hub = RecordingHub(cached=set(), root=tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)

    first = assets.path("voices/af_heart.pt")
    second = assets.path("voices/af_heart.pt")

    # Offline attempt, then one fetch. The second call is served from memory,
    # so a long-lived daemon does not re-resolve what it already holds.
    assert hub.calls == [("voices/af_heart.pt", True), ("voices/af_heart.pt", False)]
    assert first == second


def test_every_voice_resolves_to_a_file_path_not_a_bare_id(tmp_path: Path) -> None:
    hub = RecordingHub(cached={"voices/bm_daniel.pt"}, root=tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)

    resolved = assets.voice_path("bm_daniel")

    # The engine hands the pipeline a path on purpose: given a bare id it would
    # resolve the pack through the model host on every load.
    assert resolved.endswith(".pt")
    assert hub.calls == [("voices/bm_daniel.pt", True)]


def test_a_missing_asset_that_cannot_be_fetched_is_reported_clearly() -> None:
    def refuse(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        msg = f"no route to host for {filename}"
        raise OSError(msg)

    assets = KokoroAssets(repo_id=REPO, download=refuse)

    with pytest.raises(ModelAssetError) as raised:
        assets.path("config.json")

    # The message must name the asset without pasting the transport error,
    # which can carry a URL and proxy details.
    assert "config.json" in str(raised.value)
    assert "no route to host" not in str(raised.value)


def test_resolution_is_recorded_per_asset(tmp_path: Path) -> None:
    hub = RecordingHub(cached={"config.json", "voices/af_heart.pt"}, root=tmp_path)
    assets = KokoroAssets(repo_id=REPO, download=hub.download)

    assets.path("config.json")
    assets.voice_path("af_heart")
    assets.path("config.json")

    # Distinct assets resolve independently; a repeat costs nothing.
    assert hub.calls == [("config.json", True), ("voices/af_heart.pt", True)]


# -- a broken cache is not the same as an absent file ---------------------


def test_an_unreadable_cache_is_not_treated_as_a_cache_miss() -> None:
    attempts: list[bool] = []

    def guarded(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, filename
        attempts.append(local_files_only)
        if local_files_only:
            # Not "absent": the cache is there and cannot be read.
            raise PermissionError(13, "Permission denied")
        return "/should/not/be/reached"

    assets = KokoroAssets(repo_id=REPO, download=guarded)

    with pytest.raises(ModelAssetError):
        assets.path("config.json")

    # Falling back on any local failure turns a local permissions problem into
    # a network request, and reports the network error as the cause, which
    # hides the real one. Only an absent file justifies going out.
    assert attempts == [True]


def test_a_genuinely_absent_file_is_still_fetched(tmp_path: Path) -> None:
    attempts: list[bool] = []

    def absent_then_available(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id
        attempts.append(local_files_only)
        if local_files_only:
            raise FileNotFoundError(2, "not cached")
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset")
        return str(path)

    assets = KokoroAssets(repo_id=REPO, download=absent_then_available)

    assets.path("config.json")

    assert attempts == [True, False]


def test_an_unreadable_cache_names_the_asset_without_the_transport_error() -> None:
    def guarded(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        raise PermissionError(13, f"Permission denied reading /private/cache/{filename}")

    assets = KokoroAssets(repo_id=REPO, download=guarded)

    with pytest.raises(ModelAssetError) as raised:
        assets.path("config.json")

    assert "config.json" in str(raised.value)
    assert "/private/cache" not in str(raised.value)


# -- the engine must hand the pipeline a path, not a voice id -------------


class RecordingPipeline:
    """Stands in for the upstream pipeline, recording how the voice arrived."""

    def __init__(self) -> None:
        self.voices: list[str] = []

    def __call__(self, text: str, voice: str, speed: float) -> list[object]:
        del text, speed
        self.voices.append(voice)
        return []


def test_synthesis_passes_a_resolved_path_rather_than_a_voice_id(tmp_path: Path) -> None:
    from aitts.engine import SynthesisError  # noqa: PLC0415
    from aitts.engines.kokoro import KokoroEngine  # noqa: PLC0415

    hub = RecordingHub(cached={"voices/af_heart.pt"}, root=tmp_path)
    pipeline = RecordingPipeline()

    class PipelinelessEngine(KokoroEngine):
        def _pipeline(self, voice: str) -> object:
            del voice
            return pipeline

    engine = PipelinelessEngine(assets=KokoroAssets(repo_id=REPO, download=hub.download))
    # No audio comes back from the stub, so synthesis fails after the call we
    # care about has already been made.
    with pytest.raises(SynthesisError):
        engine.synthesize("hello", "af_heart", 1.0, tmp_path / "out.wav")

    # This is the whole network fix: given a bare id the upstream pipeline
    # resolves the voice pack through the model host on every load. Given a
    # path ending in .pt it reads the file. Nothing else enforced this.
    assert pipeline.voices
    assert pipeline.voices[0].endswith("voices/af_heart.pt")
    assert pipeline.voices[0] != "af_heart"
