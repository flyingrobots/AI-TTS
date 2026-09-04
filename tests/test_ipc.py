# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""End-to-end over the Unix socket: the protocol of architecture.md §5."""

from __future__ import annotations

import asyncio
import json
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.model import Priority, State
from aitts.playback import FakeSink, PlaybackController

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("daemon NDJSON wire contract in docs/design/architecture.md section 5"),
]


async def rpc(sock: Path, payload: dict[str, Any]) -> dict[str, Any]:
    reader, writer = await asyncio.open_unix_connection(str(sock))
    writer.write(json.dumps(payload).encode() + b"\n")
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    result: dict[str, Any] = json.loads(line)
    return result


@pytest.fixture
async def daemon(tmp_path: Path) -> Any:
    # AF_UNIX paths are capped at 104 bytes on macOS; pytest tmp_paths exceed
    # that, so the socket lives in a short-lived $TMPDIR directory instead.
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-"))
    d = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel", "af_bella"]),
        sink=FakeSink(auto_finish_ms=5),
        workers=2,
        socket_path=sock_dir / "d.sock",
    )
    await d.start()
    yield d
    await d.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


async def test_submit_fails_closed_to_confidential(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "submit", "text": "secret thing"})
    assert res["ok"] is True
    assert res["state"] == "Queued"
    assert res["sensitivity"] == "confidential"
    assert res["eligible_engines"] == ["local"]
    assert res["id"].startswith("utt_")


async def test_submit_echoes_declared_sensitivity(daemon: Daemon) -> None:
    res = await rpc(
        daemon.socket_path, {"op": "submit", "text": "release note", "sensitivity": "public"}
    )
    assert res["sensitivity"] == "public"


async def test_paused_daemon_advertises_spooling_and_accepts_speech(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    status = await rpc(daemon.socket_path, {"op": "status"})
    assert status["state"] == "accepting"
    assert status["playback_state"] == "paused"
    assert status["accepting_speech"] is True
    assert status["playback_held"] is True
    assert status["submission_disposition"] == "spooled_until_resume"
    assert status["submission_guidance"].startswith("Speak freely")

    submitted = await rpc(daemon.socket_path, {"op": "submit", "text": "meeting update"})
    assert submitted["ok"] is True
    assert submitted["accepted"] is True
    assert submitted["playback_held"] is True
    assert submitted["submission_disposition"] == "spooled_until_resume"
    assert submitted["submission_guidance"].startswith("Speak freely")


async def test_submit_without_text_is_bad_request(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "submit"})
    assert res["ok"] is False
    assert res["error"]["type"] == "bad_request"


async def test_subscribe_sees_the_full_lifecycle(daemon: Daemon) -> None:
    reader, writer = await asyncio.open_unix_connection(str(daemon.socket_path))
    writer.write(b'{"op": "subscribe"}\n')
    await writer.drain()
    ack = json.loads(await reader.readline())
    assert ack["ok"] is True

    sub = await rpc(daemon.socket_path, {"op": "submit", "text": "hello"})
    utt_id = sub["id"]
    seen: list[tuple[str, str]] = []
    while ("Playing", "Played") not in seen:
        event = json.loads(await asyncio.wait_for(reader.readline(), timeout=5))
        assert event["event"] == "state_changed"
        if event["id"] == utt_id:
            seen.append((event["from"], event["to"]))
    assert ("Queued", "Synthesizing") in seen
    assert ("Synthesizing", "Ready") in seen
    assert ("Ready", "Playing") in seen
    writer.close()
    await writer.wait_closed()


async def test_list_both_queues(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})  # hold playback so items pile up
    a = await rpc(daemon.socket_path, {"op": "submit", "text": "a"})
    res_in = await rpc(daemon.socket_path, {"op": "list", "queue": "input"})
    assert res_in["ok"] is True

    async def in_playback() -> bool:
        res = await rpc(daemon.socket_path, {"op": "list", "queue": "playback"})
        items: list[dict[str, Any]] = res["items"]
        return any(i["id"] == a["id"] for i in items)

    await wait_for_async(in_playback)


async def wait_for_async(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        if asyncio.get_running_loop().time() > deadline:
            msg = "condition not met before timeout"
            raise AssertionError(msg)
        await asyncio.sleep(0.01)


async def test_list_requires_valid_queue(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "list", "queue": "everything"})
    assert res["ok"] is False
    assert res["error"]["type"] == "bad_request"


async def test_clear_requires_naming_a_queue(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "clear"})
    assert res["ok"] is False
    assert res["error"]["type"] == "bad_request"


async def test_cancel_queued_ok_and_missing_id_not_found(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    sub = await rpc(daemon.socket_path, {"op": "submit", "text": "x"})
    res = await rpc(daemon.socket_path, {"op": "cancel", "id": sub["id"]})
    assert res["ok"] is True or res["error"]["type"] == "illegal_state"  # may already be Ready
    res2 = await rpc(daemon.socket_path, {"op": "cancel", "id": "utt_nope"})
    assert res2["ok"] is False
    assert res2["error"]["type"] == "not_found"


async def test_unknown_op_is_bad_request(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "frobnicate"})
    assert res["ok"] is False
    assert res["error"]["type"] == "bad_request"


async def test_malformed_json_gets_error_not_disconnect(daemon: Daemon) -> None:
    reader, writer = await asyncio.open_unix_connection(str(daemon.socket_path))
    writer.write(b"this is not json\n")
    await writer.drain()
    res = json.loads(await reader.readline())
    assert res["ok"] is False
    assert res["error"]["type"] == "bad_request"
    writer.write(b'{"op": "status"}\n')
    await writer.drain()
    res2 = json.loads(await reader.readline())
    assert res2["ok"] is True
    writer.close()
    await writer.wait_closed()


async def test_socket_is_user_only(daemon: Daemon) -> None:
    mode = stat.S_IMODE(daemon.socket_path.stat().st_mode)
    assert mode == 0o600


async def test_status_reports_shape(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "status"})
    assert res["ok"] is True
    assert res["state"] == "accepting"
    assert res["playback_state"] in {"idle", "playing", "paused", "synthesizing"}
    assert res["accepting_speech"] is True
    assert "counts" in res
    assert res["engine"] == "fake"


async def test_idle_global_pause_survives_daemon_restart(tmp_path: Path) -> None:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-pause-"))
    first = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(),
        socket_path=sock_dir / "first.sock",
    )
    await first.start()
    try:
        paused = await rpc(first.socket_path, {"op": "pause"})
        assert paused["held"] is True
        assert (await rpc(first.socket_path, {"op": "status"}))["playback_state"] == "paused"
    finally:
        await first.stop()

    restored_sink = FakeSink()
    restored = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=restored_sink,
        socket_path=sock_dir / "restored.sock",
    )
    await restored.start()
    try:
        assert (await rpc(restored.socket_path, {"op": "status"}))["playback_state"] == "paused"
        submitted = await rpc(
            restored.socket_path,
            {"op": "submit", "text": "wait until the meeting ends"},
        )
        for _ in range(100):
            utterance = restored.store.get(submitted["id"])
            if utterance is not None and utterance.state is State.READY:
                break
            await asyncio.sleep(0.005)
        queued = restored.store.get(submitted["id"])
        assert queued is not None
        assert queued.state is State.READY
        assert restored_sink.started == []
        await rpc(restored.socket_path, {"op": "resume"})
        for _ in range(100):
            if restored_sink.started:
                break
            await asyncio.sleep(0.005)
        assert len(restored_sink.started) == 1
    finally:
        await restored.stop()
        shutil.rmtree(sock_dir, ignore_errors=True)


async def test_resume_recovers_after_playback_worker_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-playback-recovery-"))
    sink = FakeSink()
    original_run = PlaybackController.run
    crash_requested = asyncio.Event()
    crash_observed = asyncio.Event()
    attempts = 0

    async def fail_once(controller: PlaybackController) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await crash_requested.wait()
            crash_observed.set()
            msg = "simulated playback worker failure"
            raise RuntimeError(msg)
        await original_run(controller)

    monkeypatch.setattr(PlaybackController, "run", fail_once)
    d = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=sink,
        socket_path=sock_dir / "d.sock",
    )
    await d.start()
    try:
        await rpc(d.socket_path, {"op": "pause"})
        submitted = await rpc(
            d.socket_path,
            {"op": "submit", "text": "play this when the meeting ends"},
        )

        async def is_ready() -> bool:
            item = d.store.get(submitted["id"])
            return item is not None and item.state is State.READY

        await wait_for_async(is_ready)
        crash_requested.set()
        await crash_observed.wait()
        await asyncio.sleep(0)

        resumed = await rpc(d.socket_path, {"op": "resume"})
        assert resumed["held"] is False

        async def playback_started() -> bool:
            return len(sink.started) == 1

        await wait_for_async(playback_started, timeout=0.25)
        assert "playback worker failed; restarting" in caplog.text
    finally:
        await d.stop()
        shutil.rmtree(sock_dir, ignore_errors=True)


async def test_voices_lists_engine_voices(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "voices"})
    assert res["ok"] is True
    assert res["voices"] == ["bm_daniel", "af_bella"]


async def test_settings_get_and_set(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "settings"})
    assert res["ok"] is True
    assert "voice" in res["settings"]
    res2 = await rpc(daemon.socket_path, {"op": "settings", "set": {"voice": "af_bella"}})
    assert res2["settings"]["voice"] == "af_bella"
    res3 = await rpc(daemon.socket_path, {"op": "settings", "set": {"voice": "nope"}})
    assert res3["ok"] is False
    assert res3["error"]["type"] == "bad_request"


async def test_cache_cap_setting_immediately_evicts_only_terminal_audio(
    daemon: Daemon, tmp_path: Path
) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    cache_dir = tmp_path / "cache"
    terminal_path = cache_dir / "terminal.wav"
    terminal_path.write_bytes(b"done")
    terminal = daemon.store.submit("done", voice="bm_daniel", speed=1.0)
    daemon.store.transition(terminal.id, State.SYNTHESIZING)
    daemon.store.transition(terminal.id, State.READY, audio_path=str(terminal_path))
    daemon.store.transition(terminal.id, State.PLAYING)
    daemon.store.transition(terminal.id, State.PLAYED)

    ready_path = cache_dir / "ready.wav"
    ready_path.write_bytes(b"owed")
    ready = daemon.store.submit("owed", voice="bm_daniel", speed=1.0)
    daemon.store.transition(ready.id, State.SYNTHESIZING)
    daemon.store.transition(ready.id, State.READY, audio_path=str(ready_path))

    response = await rpc(
        daemon.socket_path,
        {"op": "settings", "set": {"cache_max_bytes": "4"}},
    )
    history = await rpc(daemon.socket_path, {"op": "history"})
    ready_after = daemon.store.get(ready.id)

    assert {
        "response": response,
        "terminal_exists": terminal_path.exists(),
        "ready": (ready_path.exists(), None if ready_after is None else ready_after.state),
        "history": [(item["id"], item["audio_cached"]) for item in history["items"]],
    } == {
        "response": {
            "ok": True,
            "settings": {
                "voice": "bm_daniel",
                "speed": 1.0,
                "cache_max_bytes": 4,
            },
        },
        "terminal_exists": False,
        "ready": (True, State.READY),
        "history": [(terminal.id, False)],
    }


async def test_history_after_playback(daemon: Daemon) -> None:
    sub = await rpc(daemon.socket_path, {"op": "submit", "text": "remembered"})

    async def played() -> bool:
        res = await rpc(daemon.socket_path, {"op": "history"})
        items: list[dict[str, Any]] = res["items"]
        return any(i["id"] == sub["id"] and i["final_state"] == "Played" for i in items)

    await wait_for_async(played)


async def test_urgent_priority_jumps_the_plan(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    normal = await rpc(daemon.socket_path, {"op": "submit", "text": "later"})
    urgent = await rpc(daemon.socket_path, {"op": "submit", "text": "now", "priority": "urgent"})

    async def ordered() -> bool:
        res = await rpc(daemon.socket_path, {"op": "list", "queue": "playback"})
        ids = [i["id"] for i in res["items"]]
        return urgent["id"] in ids and normal["id"] in ids

    await wait_for_async(ordered)
    res = await rpc(daemon.socket_path, {"op": "list", "queue": "playback"})
    ids = [i["id"] for i in res["items"]]
    assert ids.index(urgent["id"]) < ids.index(normal["id"])


async def test_status_streams_live_position_while_playing(tmp_path: Path) -> None:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-"))
    sink = FakeSink()  # manual: stays playing until told otherwise
    d = Daemon(
        home=tmp_path / "pos",
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=sink,
        socket_path=sock_dir / "d.sock",
    )
    await d.start()
    try:
        await rpc(d.socket_path, {"op": "submit", "text": "hello"})

        async def playing() -> bool:
            res = await rpc(d.socket_path, {"op": "status"})
            return bool(res["playback_state"] == "playing")

        await wait_for_async(playing)
        sink.advance_to(4321)
        res = await rpc(d.socket_path, {"op": "status"})
        assert res["current"]["position_ms"] == 4321
    finally:
        await d.stop()
        shutil.rmtree(sock_dir, ignore_errors=True)


async def test_snapshot_returns_everything_in_one_request(daemon: Daemon) -> None:
    res = await rpc(daemon.socket_path, {"op": "snapshot"})
    assert res["ok"] is True
    assert res["status"]["state"] == "accepting"
    assert res["status"]["playback_state"] in {
        "idle",
        "playing",
        "paused",
        "synthesizing",
    }
    for key in ("playback", "input", "plan", "history", "voices", "settings"):
        assert key in res
    assert res["voices"] == ["bm_daniel", "af_bella"]
    assert "voice" in res["settings"]


async def test_history_items_carry_finished_at(daemon: Daemon) -> None:
    sub = await rpc(daemon.socket_path, {"op": "submit", "text": "timed"})

    async def played() -> bool:
        res = await rpc(daemon.socket_path, {"op": "history"})
        items: list[dict[str, Any]] = res["items"]
        return any(i["id"] == sub["id"] for i in items)

    await wait_for_async(played)
    res = await rpc(daemon.socket_path, {"op": "history"})
    item = next(i for i in res["items"] if i["id"] == sub["id"])
    assert isinstance(item["finished_at"], float)
    assert item["finished_at"] >= item["enqueued_at"]


async def test_snapshot_plan_is_merged_in_plan_order(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    first = await rpc(daemon.socket_path, {"op": "submit", "text": "first"})
    urgent = await rpc(daemon.socket_path, {"op": "submit", "text": "now", "priority": "urgent"})
    res = await rpc(daemon.socket_path, {"op": "snapshot"})
    ids = [i["id"] for i in res["plan"]]
    assert urgent["id"] in ids
    assert first["id"] in ids
    assert ids.index(urgent["id"]) < ids.index(first["id"])


async def test_requeue_uses_fresh_priority_and_preserves_original_history(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    original = daemon.store.submit(
        "historical alert", voice="bm_daniel", speed=1.0, priority=Priority.URGENT
    )
    daemon.store.transition(original.id, State.CANCELLED)
    backlog = await rpc(daemon.socket_path, {"op": "submit", "text": "already waiting"})

    normal = await rpc(daemon.socket_path, {"op": "requeue", "id": original.id})
    assert normal["ok"] is True
    assert normal["priority"] == "normal"

    snapshot = await rpc(daemon.socket_path, {"op": "snapshot"})
    plan = snapshot["plan"]
    ids = [item["id"] for item in plan]
    assert ids.index(backlog["id"]) < ids.index(normal["id"])
    original_history = next(item for item in snapshot["history"] if item["id"] == original.id)
    assert original_history["priority"] == "urgent"

    urgent = await rpc(
        daemon.socket_path,
        {"op": "requeue", "id": original.id, "priority": "urgent"},
    )
    assert urgent["priority"] == "urgent"
    snapshot = await rpc(daemon.socket_path, {"op": "snapshot"})
    ids = [item["id"] for item in snapshot["plan"]]
    assert ids.index(urgent["id"]) < ids.index(backlog["id"]) < ids.index(normal["id"])


async def test_requeue_rejects_bad_priority_and_nonterminal_target(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    queued = await rpc(daemon.socket_path, {"op": "submit", "text": "still active"})
    bad_priority = await rpc(
        daemon.socket_path,
        {"op": "requeue", "id": queued["id"], "priority": "whenever"},
    )
    assert bad_priority["ok"] is False
    assert bad_priority["error"]["type"] == "bad_request"

    nonterminal = await rpc(
        daemon.socket_path,
        {"op": "requeue", "id": queued["id"], "priority": "normal"},
    )
    assert nonterminal["ok"] is False
    assert nonterminal["error"]["type"] == "illegal_state"


async def test_reorder_replaces_the_complete_pending_plan(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    submitted = [
        await rpc(daemon.socket_path, {"op": "submit", "text": text})
        for text in ("first", "second", "third")
    ]
    reordered_ids = [item["id"] for item in reversed(submitted)]

    reordered = await rpc(
        daemon.socket_path,
        {"op": "reorder", "ids": reordered_ids},
    )
    snapshot = await rpc(daemon.socket_path, {"op": "snapshot"})

    assert reordered == {"ok": True, "ids": reordered_ids}
    assert [item["id"] for item in snapshot["plan"]] == reordered_ids

    stale = await rpc(
        daemon.socket_path,
        {"op": "reorder", "ids": reordered_ids[:-1]},
    )
    assert stale["ok"] is False
    assert stale["error"]["type"] == "bad_request"
    assert "complete pending plan" in stale["error"]["message"]


async def test_unified_clear_queue_cancels_upcoming_work(daemon: Daemon) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    submitted = [
        await rpc(daemon.socket_path, {"op": "submit", "text": text})
        for text in ("one", "two", "three")
    ]
    cleared = await rpc(daemon.socket_path, {"op": "clear", "queue": "queue"})
    assert cleared == {"ok": True, "cleared": 3}
    for item in submitted:
        got = await rpc(daemon.socket_path, {"op": "get", "id": item["id"]})
        assert got["item"]["state"] == "Cancelled"


async def test_removing_ready_queue_item_keeps_cached_audio(daemon: Daemon, tmp_path: Path) -> None:
    await rpc(daemon.socket_path, {"op": "pause"})
    cached = tmp_path / "ready.wav"
    cached.write_bytes(b"reusable audio")
    item = daemon.store.submit("ready", voice="bm_daniel", speed=1.0)
    daemon.store.transition(item.id, State.SYNTHESIZING)
    daemon.store.transition(item.id, State.READY, audio_path=str(cached), duration_ms=10)

    removed = await rpc(daemon.socket_path, {"op": "cancel", "id": item.id})

    assert removed["ok"] is True
    assert removed["state"] == "Cancelled"
    assert cached.read_bytes() == b"reusable audio"


async def test_remove_and_clear_history_keep_cached_audio_and_active_work(
    daemon: Daemon, tmp_path: Path
) -> None:
    cached = tmp_path / "cached.wav"
    cached.write_bytes(b"still cached")
    first = daemon.store.submit("first", voice="bm_daniel", speed=1.0)
    daemon.store.transition(first.id, State.SYNTHESIZING)
    daemon.store.transition(first.id, State.READY, audio_path=str(cached), duration_ms=10)
    daemon.store.transition(first.id, State.PLAYING)
    daemon.store.transition(first.id, State.PLAYED, played_ms=10)
    second = daemon.store.submit("second", voice="bm_daniel", speed=1.0)
    daemon.store.transition(second.id, State.CANCELLED)
    active = daemon.store.submit("active", voice="bm_daniel", speed=1.0)

    removed = await rpc(daemon.socket_path, {"op": "remove_history", "id": first.id})
    assert removed == {"ok": True, "removed": 1, "id": first.id}
    assert cached.read_bytes() == b"still cached"
    assert daemon.store.get(first.id) is None

    cleared = await rpc(daemon.socket_path, {"op": "clear", "queue": "history"})
    assert cleared == {"ok": True, "cleared": 1}
    assert daemon.store.history() == []
    assert daemon.store.get(active.id) is not None
