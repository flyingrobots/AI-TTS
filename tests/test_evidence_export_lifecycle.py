# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Export owns its files until the archive worker finishes, even after cancellation."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

import pytest

from aitts.adapters.clip_evidence import ClipEvidence
from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import State
from aitts.playback import FakeSink
from tests.test_ipc import wait_for_async

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "PR #26: reports protect their source/audio until the export worker finishes"
    ),
]


@pytest.mark.parametrize(
    ("operation", "cancel_request"),
    [
        ("storage", False),
        ("storage", True),
        ("purge_cache", False),
        ("settings", False),
        ("clear", False),
    ],
)
async def test_inflight_report_preserves_files_across_deletion(  # noqa: PLR0915 - gated export/delete/release protocol
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, *, cancel_request: bool
) -> None:
    # An event gate controls the interleaving; no elapsed time establishes safety.
    # Retire when export ownership disappears or a stronger schedule test subsumes it.
    sockets = tempfile.TemporaryDirectory(prefix="aitts-export-")
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(["v"]),
        sink=FakeSink(),
        socket_path=Path(sockets.name) / "d.sock",
        input_activity=FakeInputActivity(active=False),
    )
    item = daemon.store.submit("source", voice="v", speed=1.0)
    daemon.store.transition(item.id, State.SYNTHESIZING)
    folder = tmp_path / "cache" / item.id
    folder.mkdir()
    audio = folder / f"{item.id}.wav"
    audio.write_bytes(b"audio")
    (folder / "source.txt").write_text("source")
    daemon.store.transition(item.id, State.READY, audio_path=str(audio))
    daemon.store.transition(item.id, State.CANCELLED)
    await daemon.start()
    entered = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = ClipEvidence.export

    def gated_export(
        evidence: ClipEvidence, destination: Path, row: dict[str, Any], clips: list[dict[str, Any]]
    ) -> dict[str, Any]:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            message = "test did not release the export worker"
            raise TimeoutError(message)
        try:
            return original(evidence, destination, row, clips)
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(ClipEvidence, "export", gated_export)
    destination = tmp_path / "report.zip"
    request = asyncio.create_task(
        daemon.dispatch({"op": "export_evidence", "id": item.id, "destination": str(destination)})
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if cancel_request:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
        payloads: dict[str, dict[str, Any]] = {
            "storage": {"op": "storage", "delete": [item.id]},
            "purge_cache": {"op": "purge_cache"},
            "settings": {"op": "settings", "set": {"cache_max_bytes": 0}},
            "clear": {"op": "clear", "queue": "history", "delete_files": True},
        }
        await daemon.dispatch(payloads[operation])
        assert (audio.exists(), (folder / "source.txt").exists()) == (True, True)
        release.set()
        await asyncio.wait_for(finished.wait(), 5)

        async def export_released_files() -> bool:
            inventory = await daemon.dispatch({"op": "storage"})
            return all(not row["protected"] for row in inventory["entries"])

        await wait_for_async(export_released_files)
        deleted = await daemon.dispatch({"op": "storage", "delete": [item.id]})
        assert deleted["receipt"] == {"removed": 1, "protected": 0, "failed": 0}
    finally:
        release.set()
        await asyncio.gather(request, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), 5)
        await daemon.stop()
        sockets.cleanup()

    with zipfile.ZipFile(destination) as archive:
        assert archive.read(f"clips/{item.id}/audio.wav") == b"audio"


@pytest.mark.oracle("report metadata filesystem reads must not occupy the daemon event-loop thread")
async def test_export_reads_provenance_on_a_worker_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon = Daemon(home=tmp_path, engine=FakeEngine(["v"]), sink=FakeSink())
    item = daemon.store.submit("legacy", voice="v", speed=1.0)
    daemon.store.transition(item.id, State.CANCELLED)
    event_loop_thread = threading.get_ident()
    observed_threads: list[int] = []
    original = ClipEvidence.read_metadata

    def observe_read(evidence: ClipEvidence, artifact_id: str, name: str) -> dict[str, Any] | None:
        observed_threads.append(threading.get_ident())
        return original(evidence, artifact_id, name)

    monkeypatch.setattr(ClipEvidence, "read_metadata", observe_read)
    try:
        await daemon.dispatch(
            {"op": "export_evidence", "id": item.id, "destination": str(tmp_path / "report.zip")}
        )
        assert observed_threads, "export must read provenance metadata"
        assert event_loop_thread not in observed_threads
    finally:
        await daemon.stop()
