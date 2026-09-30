# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Inventory and explicit retention for owned generated clip directories."""

from __future__ import annotations

import shutil
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class GeneratedStorage:
    """Manage audio and sidecars together, preserving active/pending artifacts."""

    def __init__(self, root: Path) -> None:
        """Bind the owned cache directory."""
        self.root = root

    def inventory(self, protected: set[str]) -> list[dict[str, Any]]:
        """Describe legacy WAVs and new per-clip directories as one entry each."""
        rows: dict[str, dict[str, Any]] = {}
        for path in self.root.iterdir():
            if path.is_symlink():
                continue
            if path.is_dir():
                identity = path.name
                files = [
                    member
                    for member in path.iterdir()
                    if member.is_file() and not member.is_symlink()
                ]
            elif path.suffix == ".wav":
                identity = path.stem
                files = [path]
            else:
                continue
            row = rows.setdefault(
                identity,
                {
                    "id": identity,
                    "bytes": 0,
                    "modified_at": 0.0,
                    "protected": identity in protected,
                    "preview": identity,
                },
            )
            for member in files:
                try:
                    info = member.stat()
                except FileNotFoundError:
                    continue
                row["bytes"] += info.st_size
                row["modified_at"] = max(row["modified_at"], info.st_mtime)
                if member.name.endswith(".part"):
                    row["protected"] = True
                if member.name == "source.txt":
                    with member.open(encoding="utf-8", errors="replace") as source:
                        row["preview"] = source.read(160).replace("\n", " ")
        return sorted(rows.values(), key=lambda row: row["modified_at"], reverse=True)

    def remove(self, identities: set[str], protected: set[str]) -> dict[str, int]:
        """Delete only currently eligible owned artifacts; report partial failures."""
        removed = skipped = failed = 0
        for row in self.inventory(protected):
            identity = str(row["id"])
            if identity not in identities:
                continue
            if row["protected"]:
                skipped += 1
                continue
            try:
                directory = self.root / identity
                if directory.is_dir() and not directory.is_symlink():
                    shutil.rmtree(directory)
                legacy = self.root / f"{identity}.wav"
                if not legacy.is_symlink():
                    legacy.unlink(missing_ok=True)
                removed += 1
            except OSError:
                failed += 1
        return {"removed": removed, "protected": skipped, "failed": failed}

    def expired(self, protected: set[str], days: int, *, now: float | None = None) -> set[str]:
        """Select inactive entries older than the opt-in retention window."""
        if days <= 0:
            return set()
        cutoff = (time.time() if now is None else now) - days * 86400
        return {
            str(row["id"])
            for row in self.inventory(protected)
            if not row["protected"] and row["modified_at"] < cutoff
        }
