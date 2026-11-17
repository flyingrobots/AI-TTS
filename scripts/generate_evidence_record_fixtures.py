# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Regenerate the Python clip-evidence record fixture for the aitts-artifacts crate.

Run from the repository root: ``uv run python scripts/generate_evidence_record_fixtures.py``.
``records/`` is the evidence that the Python ``ClipEvidence`` writers leave for the
scenario below. The wall clock starts at ``WALL`` and the monotonic clock at
``MONOTONIC``; each reading adds one second. The log limit is lowered to
``LOG_LIMIT`` bytes so that rotation and the oversized-event rule happen.
"""

from __future__ import annotations

import itertools
import shutil
from pathlib import Path
from unittest import mock

from aitts.adapters.clip_evidence import ClipEvidence
from aitts.model import SynthesisWork

FIXTURES = Path("crates/aitts-artifacts/tests/fixtures/records")
WALL = 1_800_000_000.0
MONOTONIC = 100.0
LOG_LIMIT = 400
SESSION = "fixture-session"
RUNTIME = {"os": "fixture", "architecture": "fixture"}


def main() -> None:
    """Run the scenario against the Python writers."""
    shutil.rmtree(FIXTURES, ignore_errors=True)
    wall = itertools.count(WALL)
    monotonic = itertools.count(MONOTONIC)
    with (
        mock.patch("aitts.adapters.clip_evidence.time.time", side_effect=lambda: next(wall)),
        mock.patch(
            "aitts.adapters.clip_evidence.time.monotonic", side_effect=lambda: next(monotonic)
        ),
        mock.patch("aitts.adapters.clip_evidence._MAX_LOG_BYTES", LOG_LIMIT),
    ):
        evidence = ClipEvidence(FIXTURES)
        evidence.session = SESSION
        evidence.runtime = RUNTIME
        work = SynthesisWork(
            id="clip-a",
            utterance_id="utt_0001",
            segment_index=0,
            text="Hello, ünïcode world.",
            voice="af_heart",
            speed=1.25,
        )
        evidence.prepare(work, "kokoro")
        evidence.record("clip-a", "synthesis", "chunk", index=1, text="ünï")
        evidence.generated("clip-a", {"model": "kokoro-82m", "voice": "af_heart"})
        evidence.record("clip-a", "playback", "played", playback_session="p1")
        evidence.record("clip-a", "playback", "big", blob="x" * LOG_LIMIT)
        for index in range(6):
            evidence.record("clip-b", "synthesis", "chunk", index=index)


if __name__ == "__main__":
    main()
