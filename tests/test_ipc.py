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
from aitts.playback import FakeSink


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
    assert res["state"] in {"idle", "playing", "paused", "synthesizing", "held"}
    assert "counts" in res
    assert res["engine"] == "fake"


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
            return bool(res["state"] == "playing")

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
    assert res["status"]["state"] in {"idle", "playing", "paused", "synthesizing"}
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
