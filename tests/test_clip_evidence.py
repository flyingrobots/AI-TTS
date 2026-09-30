# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Per-artifact evidence and selected-item export contracts."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest
from blake3 import blake3

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.adapters.clip_evidence import ClipEvidence
from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.adapters.playback_schedule import ImmediatePlaybackSchedule
from aitts.engine import FakeEngine
from aitts.model import State, SynthesisWork
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "per-file source, generation provenance, playback causes, and local evidence ZIP contract"
    ),
]


def test_report_partitions_audio_and_logs_and_preserves_generation_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = {"packages": {"kokoro": "generation-version"}}
    monkeypatch.setattr("aitts.adapters.clip_evidence.runtime_metadata", lambda: dict(runtime))
    evidence = ClipEvidence(tmp_path / "cache")
    artifacts = FileAudioArtifacts(evidence.root)
    work = SynthesisWork("clip", "parent", 0, "abc", "v", 1.25)
    evidence.submitted("parent", "Original source", {"op": "submit", "voice": "v", "origin": "CLI"})
    candidate = artifacts.target(work.id)
    evidence.prepare(work, "fake")
    FakeEngine(["v"]).synthesize(work.text, work.voice, work.speed, candidate)
    evidence.audio_generated(work.id, candidate)
    audio = artifacts.publish(work.id, candidate)
    expected_audio = audio.read_bytes()
    evidence.record(
        "clip", "playback", "pause_requested", cause="microphone", playback_session="one"
    )
    evidence.record("other", "playback", "secret_other_item")
    runtime = {"packages": {"kokoro": "export-version"}}
    destination = tmp_path / "report.zip"
    evidence.export(
        destination,
        {"text": "Original source"},
        [{"artifact_id": "clip", "text": "abc", "audio_path": str(audio)}],
    )
    with zipfile.ZipFile(destination) as archive:
        generation = json.loads(archive.read("clips/clip/generation.json"))
        manifest = json.loads(archive.read("manifest.json"))
        audio_meta = json.loads(archive.read("clips/clip/audio.json"))
        synthesis = [
            json.loads(line) for line in archive.read("clips/clip/synthesis.jsonl").splitlines()
        ]
        playback = [
            json.loads(line) for line in archive.read("clips/clip/playback.jsonl").splitlines()
        ]
        observed = {
            "source": archive.read("clips/clip/source.txt"),
            "original": archive.read("source.txt"),
            "audio": archive.read("clips/clip/audio.wav"),
            "generated_with": generation["runtime"],
            "exported_with": manifest["export_runtime"],
            "voice": generation["voice"],
            "speed": generation["speed"],
            "audio_blake3": audio_meta["blake3"],
            "export_blake3": manifest["clips"][0]["audio_blake3"],
            "synthesis": [event["event"] for event in synthesis],
            "playback": [
                (event["event"], event["cause"], event["playback_session"]) for event in playback
            ],
            "unrelated": any("other" in name for name in archive.namelist()),
            "mode": stat.S_IMODE(destination.stat().st_mode),
            "same_directory": audio.parent == evidence.root / work.id,
        }
    assert observed == {
        "source": b"abc",
        "original": b"Original source",
        "audio": expected_audio,
        "generated_with": {"packages": {"kokoro": "generation-version"}},
        "exported_with": {"packages": {"kokoro": "export-version"}},
        "voice": "v",
        "speed": 1.25,
        "audio_blake3": blake3(expected_audio).hexdigest(),
        "export_blake3": blake3(expected_audio).hexdigest(),
        "synthesis": ["started"],
        "playback": [("pause_requested", "microphone", "one")],
        "unrelated": False,
        "mode": 0o600,
        "same_directory": True,
    }


def test_source_identity_matches_blake3_utf8_known_vector(tmp_path: Path) -> None:
    evidence = ClipEvidence(tmp_path)
    evidence.submitted(
        "clip", "abc", {"op": "submit", "text": "abc", "origin": "CLI", "speed": 1.2}
    )
    request = evidence.read_metadata("clip", "request.json")
    assert request is not None
    assert {key: request[key] for key in ("source_blake3", "arguments")} == {
        "source_blake3": "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85",
        "arguments": {"origin": "CLI", "speed": 1.2},
    }


def test_legacy_missing_audio_reports_gaps_without_inventing_generation_metadata(
    tmp_path: Path,
) -> None:
    evidence = ClipEvidence(tmp_path / "cache")
    destination = tmp_path / "report.zip"
    receipt = evidence.export(
        destination, {"text": "old"}, [{"artifact_id": "legacy", "text": "old", "audio_path": None}]
    )
    with zipfile.ZipFile(destination) as archive:
        assert {"warnings": receipt["warnings"], "files": sorted(archive.namelist())} == {
            "warnings": [
                "legacy: generation.json was not captured",
                "legacy: synthesis.jsonl was not captured",
                "legacy: playback.jsonl was not captured",
                "legacy: cached audio is missing",
            ],
            "files": ["README.txt", "clips/legacy/source.txt", "manifest.json", "source.txt"],
        }


def test_export_refuses_to_replace_an_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        ClipEvidence(tmp_path / "cache").export(destination, {}, [])
    assert destination.read_bytes() == b"keep"


async def test_playback_causes_are_attached_to_the_actual_audio_file(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    evidence = ClipEvidence(tmp_path / "cache")
    item = store.submit("abc", voice="v", speed=1.0)
    store.transition(item.id, State.SYNTHESIZING)
    audio = evidence.directory("shared-audio") / "shared-audio.wav"
    audio.write_bytes(b"audio")
    store.transition(item.id, State.READY, audio_path=str(audio))
    store.transition(item.id, State.PLAYING)
    store.transition(item.id, State.PAUSED, played_ms=37)
    controller = PlaybackController(
        store, FakeSink(), ImmediatePlaybackSchedule(), held=True, evidence=evidence
    )
    try:
        await controller.resume(cause="menu_button")
        await controller.interrupt()
        await controller.resume(cause="input_idle")
        await controller.pause(cause="menu_button")
        rows = [
            json.loads(line) for line in (audio.parent / "playback.jsonl").read_text().splitlines()
        ]
        assert [(row["event"], row["cause"], row["utterance_id"]) for row in rows] == [
            ("resume_requested", "menu_button", item.id),
            ("pause_requested", "microphone", item.id),
            ("resume_requested", "input_idle", item.id),
            ("pause_requested", "menu_button", item.id),
        ]
    finally:
        await controller.skip()
        store.close()


def test_nested_audio_remains_in_cache_inventory_and_purge(tmp_path: Path) -> None:
    artifacts = FileAudioArtifacts(tmp_path)
    candidate = artifacts.target("clip")
    candidate.write_bytes(b"complete")
    published = artifacts.publish("clip", candidate)
    cache = FileAudioCache(tmp_path)
    assert [(entry.path, entry.size_bytes) for entry in cache.inventory()] == [(published, 8)]
    assert cache.delete(published) is True
    assert cache.inventory() == ()
