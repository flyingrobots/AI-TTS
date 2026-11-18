# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The MCP tool-call fixtures still describe the Python ``ai-tts-mcp`` server.

``tests/fixtures/mcp_tool_calls.json`` holds one case per tool call: the daemon
replies a scripted socket peer gives, the daemon requests the Python server
sent, and its exact ``tools/call`` reply. The Rust ``ai-tts mcp`` is tested
against the same cases. The daemon replies were captured once from the Python
fixture daemon (``tests/fixture_daemon.py``); each check replays them, so it is
deterministic.

Re-baseline under Python 3.12 (``UV_PYTHON=3.12 uv run --isolated --frozen
--dev python -m tests.test_mcp_tool_parity``); review the diff.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the Python ai-tts-mcp server's tools/call replies"),
    # Python 3.13 dedents docstrings; the fixtures record the 3.12 server that
    # `make install` and CI run.
    pytest.mark.skipif(
        sys.version_info[:2] != (3, 12),
        reason="fixtures record the Python 3.12 server; run with UV_PYTHON=3.12",
    ),
]

_CASES = Path(__file__).parent / "fixtures" / "mcp_tool_calls.json"
ABSENT = "/nonexistent/ai-tts.sock"

# Tool, its arguments, and the daemon operations whose captured replies the peer gives.
CALLS: list[tuple[str, dict[str, Any], list[str]]] = [
    ("speech_status", {}, ["status"]),
    ("list_speech_queue", {}, ["snapshot"]),
    ("speech_metrics", {}, ["metrics"]),
    ("list_speech_voices", {}, ["voices"]),
    ("get_caption_settings", {}, ["settings"]),
    ("pause_speech_playback", {}, ["pause"]),
    ("resume_speech_playback", {}, ["resume"]),
    ("skip_current_speech", {}, ["skip"]),
    ("restart_current_speech", {}, ["rewind"]),
    ("next_speech_chunk", {}, ["next_segment"]),
    ("previous_speech_chunk", {}, ["previous_segment"]),
    ("resume_speech_when_input_idle", {}, ["resume_when_input_idle"]),
    ("list_speech_voice_assignments", {}, ["voice_assignments"]),
    ("clear_speech_queue", {}, ["clear"]),
    ("purge_cached_audio", {}, ["purge_cache"]),
    ("speech_status", {}, ["held_status"]),
    ("get_caption_settings", {}, ["settings_captions_on"]),
    ("list_speech_queue", {}, ["snapshot_bad_id"]),
    ("speech_metrics", {}, ["metrics_integral"]),
    ("speech_status", {}, ["not_found"]),
    ("speech_status", {}, ["outside_schema"]),
    ("speech_status", {}, []),
    ("no_such_tool", {}, []),
]


def _daemon_replies() -> dict[str, Any]:
    """Capture one reply per operation from the Python fixture daemon."""
    home = Path(tempfile.mkdtemp(prefix="aitts-mcp-"))
    sock = home / "d.sock"
    env = {**os.environ, "AI_TTS_HOME": str(home), "AI_TTS_SOCKET": str(sock)}
    daemon = subprocess.Popen(  # noqa: S603 - this checkout's fixture daemon
        [sys.executable, str(Path(__file__).with_name("fixture_daemon.py"))], env=env
    )
    try:
        for _ in range(200):
            if sock.exists():
                break
            time.sleep(0.05)

        def ask(request: dict[str, Any]) -> Any:
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(sock))
                client.sendall((json.dumps(request) + "\n").encode())
                return json.loads(client.makefile("rb").readline())

        replies = {
            op: ask({"op": op})
            for op in (
                "status",
                "metrics",
                "voices",
                "settings",
                "resume",
                "skip",
                "rewind",
                "next_segment",
                "previous_segment",
                "voice_assignments",
                "purge_cache",
            )
        }
        replies["clear"] = ask({"op": "clear", "queue": "queue"})
        replies["pause"] = ask({"op": "pause"})
        ask({"op": "submit", "text": "Held speech.", "origin": "MCP"})
        replies["held_status"] = ask({"op": "status"})
        replies["snapshot"] = ask({"op": "snapshot", "limit": 1})
        replies["resume_when_input_idle"] = ask({"op": "resume_when_input_idle"})
        ask({"op": "settings", "set": {"captions_enabled": True}})
        replies["settings_captions_on"] = ask({"op": "settings"})
        bad = json.loads(json.dumps(replies["snapshot"]))
        bad["plan"][0]["id"] = "utt_not_an_id"
        replies["snapshot_bad_id"] = bad
        # A daemon may write a whole number for a float field; Pydantic dumps 2.0.
        integral = json.loads(json.dumps(replies["metrics"]))
        integral["synthesis_wait_ms"] = {"count": 1, "p50": 2, "p95": 2, "max": 2}
        replies["metrics_integral"] = integral
        replies["not_found"] = {"ok": False, "error": {"type": "not_found", "message": "no such"}}
        replies["outside_schema"] = {**replies["status"], "unexpected": 1}
        return replies
    finally:
        daemon.terminate()
        daemon.wait()


def _serve(path: str, replies: list[Any], seen: list[Any]) -> threading.Thread:
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(path)
    listener.listen()

    def answer() -> None:
        with listener:
            for reply in replies:
                connection, _ = listener.accept()
                with connection:
                    seen.append(json.loads(connection.makefile("rb").readline()))
                    connection.sendall((json.dumps(reply) + "\n").encode())

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    return thread


def run_case(tool: str, arguments: dict[str, Any], replies: list[Any]) -> dict[str, Any]:
    """Call one tool on a fresh Python server; the peer answers with ``replies``."""
    directory = tempfile.mkdtemp(prefix="aitts-peer-")
    path = str(Path(directory) / "peer.sock") if replies else ABSENT
    seen: list[Any] = []
    if replies:
        _serve(path, replies, seen)
    process = subprocess.Popen(  # noqa: S603 - this environment's own entry point
        [str(Path(sys.executable).with_name("ai-tts-mcp"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "AI_TTS_SOCKET": path},
    )
    assert process.stdin is not None
    assert process.stdout is not None
    messages: list[dict[str, Any]] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "parity", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    ]
    reply = None
    for message in messages:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        if "id" in message:
            reply = json.loads(process.stdout.readline())
    process.stdin.close()
    process.wait()
    return {
        "tool": tool,
        "arguments": arguments,
        "socket": "peer" if replies else "absent",
        "daemon_replies": replies,
        "daemon_requests": seen,
        "reply": reply,
    }


_RECORDED: list[dict[str, Any]] = json.loads(_CASES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _RECORDED, ids=[c["tool"] for c in _RECORDED])
def test_case_matches_the_python_server(case: dict[str, Any]) -> None:
    assert run_case(case["tool"], case["arguments"], case["daemon_replies"]) == case


if __name__ == "__main__":
    captured = _daemon_replies()
    cases = [run_case(tool, args, [captured[op] for op in ops]) for tool, args, ops in CALLS]
    _CASES.write_text(json.dumps(cases, indent=1) + "\n", encoding="utf-8")
