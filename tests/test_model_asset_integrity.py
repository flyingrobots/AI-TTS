# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
import re
import sys
import types
from pathlib import Path

import pytest

from aitts import model_worker
from aitts.model_catalog import MODELS

pytestmark = pytest.mark.oracle(
    "guided setup loads only model files whose SHA-256 matches the pinned catalog digest"
)

_OWNED = b"owned model asset"


def _fake_hub(monkeypatch: pytest.MonkeyPatch, content: bytes) -> list[str]:
    """Replace the setup-only network boundary with an owned local writer."""
    calls: list[str] = []

    def snapshot_download(
        *, repo_id: str, revision: str, allow_patterns: list[str], local_dir: Path
    ) -> str:
        calls.append(f"{repo_id}@{revision}")
        for filename in allow_patterns:
            path = Path(local_dir) / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return str(local_dir)

    module = types.ModuleType("huggingface_hub")
    module.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    return calls


def _owned_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    model = dataclasses.replace(
        MODELS["kokoro"],
        files=("config.json", "voices/af_heart.pt"),
        sha256={
            "config.json": hashlib.sha256(_OWNED).hexdigest(),
            "voices/af_heart.pt": hashlib.sha256(_OWNED).hexdigest(),
        },
    )
    monkeypatch.setitem(MODELS, "kokoro", model)


def _recording_engine(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    loaded: list[str] = []

    class OwnedEngine:
        def warmup(self) -> None:
            loaded.append("warmup")

    def local_engine(name: str, root: Path) -> OwnedEngine:
        del root
        loaded.append(name)
        return OwnedEngine()

    monkeypatch.setattr(model_worker, "local_engine", local_engine)
    return loaded


@pytest.mark.small
def test_every_catalog_file_has_exactly_one_pinned_sha256() -> None:
    for model in MODELS.values():
        assert set(model.sha256) == set(model.files)
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in model.sha256.values())


@pytest.mark.medium
def test_tampered_download_is_rejected_before_any_model_file_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_hub(monkeypatch, b"substituted pickle payload")
    loaded = _recording_engine(monkeypatch)
    with pytest.raises(ValueError, match="integrity"):
        model_worker.prepare("kokoro", tmp_path)
    assert calls == [f"{MODELS['kokoro'].repository}@{MODELS['kokoro'].revision}"]
    assert loaded == []


@pytest.mark.medium
def test_matching_download_is_loaded_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owned_catalog(monkeypatch)
    _fake_hub(monkeypatch, _OWNED)
    loaded = _recording_engine(monkeypatch)
    model_worker.prepare("kokoro", tmp_path)
    assert loaded == ["kokoro", "warmup"]
