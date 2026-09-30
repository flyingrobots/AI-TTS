# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Replay evidence survives independent eviction of shared audio."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("cached replay retains generation provenance when only audio is purged"),
]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("segments", [None, ("first", "second")])
async def test_replay_provenance_survives_audio_purge(
    tmp_path: Path, segments: tuple[str, ...] | None, *, legacy: bool
) -> None:
    # No daemon workers run: the store boundary seeds completed synthesis.
    # Retire only if evidence retention is replaced by a calibrated contract.
    daemon = Daemon(home=tmp_path, engine=FakeEngine(["v"]), sink=FakeSink())
    try:
        original = daemon.store.submit("source", voice="v", speed=1, spoken_segments=segments)
        expected = []
        while work := daemon.store.claim_for_synthesis():
            folder = tmp_path / "cache" / work.id
            folder.mkdir()
            audio = folder / f"{work.id}.wav"
            audio.write_bytes(b"audio")
            generation = {"artifact_id": work.id, "engine": "original-generation"}
            (folder / "generation.json").write_text(json.dumps(generation))
            expected.append((work.id, generation))
            daemon.store.finish_synthesis(work, audio_path=str(audio), duration_ms=10)
        daemon.store.transition(original.id, State.CANCELLED)
        replay = await daemon.dispatch({"op": "requeue", "id": original.id})
        daemon.store.transition(replay["id"], State.CANCELLED)
        if legacy:
            daemon.store.close()
            # Recreate the exact pre-migration table shape while audio links exist.
            with sqlite3.connect(tmp_path / "state.db") as database:
                for table in ("utterances", "utterance_segments"):
                    database.execute(f"ALTER TABLE {table} DROP COLUMN generation_artifact_id")
            daemon = Daemon(home=tmp_path, engine=FakeEngine(["v"]), sink=FakeSink())
        await daemon.dispatch({"op": "purge_cache"})
        daemon.store.close()
        daemon = Daemon(home=tmp_path, engine=FakeEngine(["v"]), sink=FakeSink())
        result = await daemon.dispatch({"op": "provenance", "id": replay["id"]})
        destination = tmp_path / "replay.zip"
        await daemon.dispatch(
            {"op": "export_evidence", "id": replay["id"], "destination": str(destination)}
        )
        with zipfile.ZipFile(destination) as archive:
            exported = [
                (key, json.loads(archive.read(f"clips/{key}/generation.json")))
                for key, _generation in expected
            ]
        assert {
            "provenance": [
                (clip["artifact_id"], clip["generation"]) for clip in result["provenance"]["clips"]
            ],
            "export": exported,
        } == {"provenance": expected, "export": expected}
    finally:
        daemon.store.close()
