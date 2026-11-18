# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Regenerate the Python generated-storage fixture for the aitts-artifacts crate.

Run from the repository root: ``uv run python scripts/generate_cache_fixtures.py``.
``cache/root`` is a cache directory as the Python daemon leaves it. Git does not keep
modification times, so ``mtimes.json`` lists them and both this script and the Rust
tests apply them before reading. ``inventory.json`` is what ``GeneratedStorage.inventory``
returns with ``PROTECTED``; ``removal.json`` is the result of ``remove(REMOVE, PROTECTED)``
on a copy and the root members left after it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from aitts.adapters.generated_storage import GeneratedStorage

FIXTURES = Path("crates/aitts-artifacts/tests/fixtures/cache")
PROTECTED = ["held"]
REMOVE = ["clip-a", "held", "streaming", "legacy", "absent"]
# The symbolic link ``linked -> clip-a`` is made by each reader; Git keeps it as a file.
MTIMES = {
    "clip-a/source.txt": 1_800_000_100.5,
    "clip-a/clip-a.wav": 1_800_000_200.5,
    "clip-a/audio.json": 1_800_000_150.5,
    "held/held.wav": 1_800_000_300.5,
    "streaming/.streaming.wav.part": 1_800_000_400.5,
    "streaming/source.txt": 1_800_000_050.5,
    "legacy.wav": 1_800_000_500.5,
    "legacy/source.txt": 1_800_000_010.5,
    "notes.txt": 1_800_000_600.5,
}


def build(root: Path) -> None:
    """Directories, a legacy WAV beside a same-named directory, a part file, and noise."""
    files: dict[str, bytes] = {
        "clip-a/source.txt": ("Line one\r\nline two\n" + "x" * 200).encode(),
        "clip-a/clip-a.wav": b"RIFF" + bytes(96),
        "clip-a/audio.json": b"{}",
        "held/held.wav": b"RIFF" + bytes(10),
        "streaming/.streaming.wav.part": b"RIFF" + bytes(20),
        "streaming/source.txt": b"bad \xff\xfe utf-8 \xe2\x82",
        "legacy.wav": b"RIFF" + bytes(30),
        "legacy/source.txt": "Ünïcode legacy".encode(),
        "notes.txt": b"not a clip",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def apply_mtimes(root: Path) -> None:
    """Set each listed file's modification time; make the symbolic link."""
    for name, mtime in MTIMES.items():
        os.utime(root / name, (mtime, mtime))
    (root / "linked").symlink_to("clip-a")


def main() -> None:
    """Write the cache, the times, and the Python results."""
    shutil.rmtree(FIXTURES, ignore_errors=True)
    build(FIXTURES / "root")
    (FIXTURES / "mtimes.json").write_text(json.dumps(MTIMES, indent=2) + "\n")
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "root"
        shutil.copytree(FIXTURES / "root", root)
        apply_mtimes(root)
        storage = GeneratedStorage(root)
        inventory = storage.inventory(set(PROTECTED))
        (FIXTURES / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
        result = storage.remove(set(REMOVE), set(PROTECTED))
        left = sorted(path.name for path in root.iterdir())
        removal = {"result": result, "left": left}
        (FIXTURES / "removal.json").write_text(json.dumps(removal, indent=2) + "\n")


if __name__ == "__main__":
    main()
