# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Regenerate the Python clip-evidence export fixture for the aitts-artifacts crate.

Run from the repository root: ``uv run python scripts/generate_evidence_fixtures.py``.
``root/`` is an evidence cache as the Python daemon leaves it. ``python-export.zip``
is what ``ClipEvidence.export`` writes for ``request.json``'s item and clips, with
each clip's ``audio_path`` taken relative to ``root/``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from aitts.adapters.clip_evidence import ClipEvidence

FIXTURES = Path("crates/aitts-artifacts/tests/fixtures/evidence")
# The export clock and runtime are inputs: pin them so the fixture names no machine.
EXPORTED_AT = 1_800_000_000.5
RUNTIME = {"os": "fixture", "architecture": "fixture"}


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def build_root(root: Path) -> None:
    """Clip ``full`` has every file; clip ``legacy`` has rotated logs and no audio."""
    full = root / "full"
    _write(full / "source.txt", "Hello, ünïcode world.")
    _write(full / "request.json", '{"arguments": {"voice": "af_heart"}}')
    _write(full / "audio.json", '{"frames": 10}')
    _write(full / "generation.json", '{"engine": "kokoro"}')
    _write(full / "model.json", '{"model": "kokoro-82m"}')
    _write(full / "synthesis.jsonl", '{"event": "started"}\n{"event": "finished"}\n')
    _write(full / "playback.jsonl", '{"event": "played"}\n')
    _write(full / "full.wav", b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(range(64)))
    legacy = root / "legacy"
    _write(legacy / "synthesis.previous.jsonl", '{"event": "old"}\n')
    _write(legacy / "synthesis.jsonl", '{"event": "new"}\n')
    _write(legacy / "logs-truncated.txt", "Earlier events were rotated out.\n")


def main() -> None:
    """Write the evidence root and the Python export of it."""
    shutil.rmtree(FIXTURES / "root", ignore_errors=True)
    build_root(FIXTURES / "root")
    request = json.loads((FIXTURES / "request.json").read_text())
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "root"
        shutil.copytree(FIXTURES / "root", root)
        clips = [
            {**clip, "audio_path": str(root / clip["audio_path"])}
            if clip.get("audio_path")
            else clip
            for clip in request["clips"]
        ]
        destination = Path(scratch) / "export.zip"
        with (
            mock.patch("aitts.adapters.clip_evidence.runtime_metadata", return_value=RUNTIME),
            mock.patch("aitts.adapters.clip_evidence.time.time", return_value=EXPORTED_AT),
        ):
            ClipEvidence(root).export(destination, request["item"], clips)
        shutil.copyfile(destination, FIXTURES / "python-export.zip")


if __name__ == "__main__":
    main()
