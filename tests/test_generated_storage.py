# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
"""Generated-file deletion and retention contracts against an owned filesystem."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aitts.adapters.generated_storage import GeneratedStorage

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "requested generated-file management: complete deletion, active protection, opt-in expiry"
    ),
]


def test_delete_removes_complete_evidence_but_protects_active_and_partial_files(
    tmp_path: Path,
) -> None:
    for identity in ("done", "active", "partial"):
        folder = tmp_path / identity
        folder.mkdir()
        (folder / "source.txt").write_text(identity)
        (folder / "playback.jsonl").write_text("event")
        (folder / ("audio.part" if identity == "partial" else "audio.wav")).write_bytes(b"audio")
    (tmp_path / "legacy.wav").write_bytes(b"legacy")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (tmp_path / "linked.wav").symlink_to(outside)
    storage = GeneratedStorage(tmp_path)
    receipt = storage.remove(
        {"done", "active", "partial", "legacy", "../outside", "linked"}, {"active"}
    )
    assert receipt == {"removed": 2, "protected": 2, "failed": 0}
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "active",
        "linked.wav",
        "outside.txt",
        "partial",
    ]
    assert outside.read_text() == "keep"
    assert (tmp_path / "active" / "audio.wav").read_bytes() == b"audio"


def test_retention_uses_last_activity_and_never_expires_protected_files(tmp_path: Path) -> None:
    now = 2_000_000.0
    for name, age in (("old", 8), ("recent", 6), ("active", 8)):
        folder = tmp_path / name
        folder.mkdir()
        audio = folder / "audio.wav"
        audio.write_bytes(b"audio")
        os.utime(audio, (now - age * 86400, now - age * 86400))
    storage = GeneratedStorage(tmp_path)
    assert storage.expired({"active"}, 0, now=now) == set()
    assert storage.expired({"active"}, 7, now=now) == {"old"}
    rows = storage.inventory({"active"})
    assert sum(row["bytes"] for row in rows) == 15
    assert {row["id"] for row in rows if row["protected"]} == {"active"}
