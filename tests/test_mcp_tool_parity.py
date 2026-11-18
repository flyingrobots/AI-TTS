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

_ID = "utt_" + "0" * 31 + "1"
# A refused call names the status reply; the peer offers it, and no request may arrive.
_REFUSED = "status"

# Tools with arguments: valid calls, Pydantic's lax conversions, and refusals.
ARGUMENT_CALLS: list[tuple[str, dict[str, Any], str]] = [
    ("enqueue_speech", {"text": "Hello."}, "submit"),
    ("enqueue_speech", {"text": "  Hello.  "}, "submit"),
    (
        "enqueue_speech",
        {
            "text": "# Title",
            "content_format": "markdown",
            "voice": "af_bella",
            "speed": 1.5,
            "sensitivity": "public",
            "priority": "urgent",
            "preempt": True,
            "source": "agent",
        },
        "submit",
    ),
    ("enqueue_speech", {"text": "Hello.", "speed": 1}, "submit"),
    ("enqueue_speech", {"text": "Hello.", "speed": "1.25"}, "submit"),
    ("enqueue_speech", {"text": "Hello.", "preempt": "yes"}, "submit"),
    ("enqueue_speech", {"text": "Hello.", "source": None, "voice": None}, "submit"),
    ("enqueue_speech", {"text": "Hello.", "unknown": 1}, "submit"),
    ("enqueue_speech", {}, _REFUSED),
    ("enqueue_speech", {"text": ""}, _REFUSED),
    ("enqueue_speech", {"text": "   "}, _REFUSED),
    ("enqueue_speech", {"text": 5}, _REFUSED),
    ("enqueue_speech", {"text": "Hello.", "speed": 3}, _REFUSED),
    ("enqueue_speech", {"text": "Hello.", "speed": "fast"}, _REFUSED),
    ("enqueue_speech", {"text": "Hello.", "priority": "low"}, _REFUSED),
    ("enqueue_speech", {"text": "Hello.", "voice": ""}, _REFUSED),
    ("enqueue_speech", {"text": "Hello.", "source": " "}, _REFUSED),
    ("enqueue_speech", {"text": "Hello.", "preempt": "maybe"}, _REFUSED),
    ("requeue_speech", {"utterance_id": _ID}, "requeue"),
    ("requeue_speech", {"utterance_id": _ID, "priority": "urgent"}, "requeue"),
    ("requeue_speech", {"utterance_id": "utt_bad"}, _REFUSED),
    ("requeue_speech", {}, _REFUSED),
    ("list_speech_history", {}, "history"),
    ("list_speech_history", {"limit": 5, "before": _ID}, "history"),
    ("list_speech_history", {"limit": "3"}, "history"),
    ("list_speech_history", {"limit": 2.0}, "history"),
    ("list_speech_history", {"limit": 0}, _REFUSED),
    ("list_speech_history", {"limit": 2.5}, _REFUSED),
    ("list_speech_history", {"before": "utt_bad"}, _REFUSED),
    ("set_captions_enabled", {"enabled": False}, "settings_set"),
    ("set_captions_enabled", {"enabled": "off"}, "settings_set"),
    ("set_captions_enabled", {"enabled": 1}, "settings_set"),
    ("set_captions_enabled", {}, _REFUSED),
    ("set_captions_enabled", {"enabled": "maybe"}, _REFUSED),
    ("set_captions_enabled", {"enabled": 2}, _REFUSED),
    ("assign_speech_voice", {"source": "agent", "voice": "af_bella"}, "assign"),
    ("assign_speech_voice", {"source": " agent "}, "release"),
    ("assign_speech_voice", {"source": "agent", "voice": None}, "release"),
    ("assign_speech_voice", {"source": ""}, _REFUSED),
    ("assign_speech_voice", {"source": "agent", "voice": " "}, _REFUSED),
    ("assign_speech_voice", {}, _REFUSED),
    ("cancel_queued_speech", {"utterance_id": _ID}, "cancel"),
    ("cancel_queued_speech", {"utterance_id": "UTT_" + "0" * 32}, _REFUSED),
]

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
    *[(tool, arguments, [op]) for tool, arguments, op in ARGUMENT_CALLS],
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
        played = ask({"op": "submit", "text": "Played speech.", "origin": "MCP"})
        for _ in range(200):
            if ask({"op": "get", "id": played["id"]})["item"]["state"] == "Played":
                break
            time.sleep(0.05)
        replies["history"] = ask({"op": "history", "limit": 5})
        replies["requeue"] = ask({"op": "requeue", "id": played["id"], "priority": "normal"})
        replies["settings_set"] = ask({"op": "settings", "set": {"captions_enabled": False}})
        replies["assign"] = ask({"op": "assign_voice", "source": "agent", "voice": "af_bella"})
        replies["release"] = ask({"op": "assign_voice", "source": "agent", "release": True})
        replies["pause"] = ask({"op": "pause"})
        replies["submit"] = ask({"op": "submit", "text": "Held speech.", "origin": "MCP"})
        pending = ask({"op": "submit", "text": "Cancelled speech.", "origin": "MCP"})
        replies["cancel"] = ask({"op": "cancel", "id": pending["id"]})
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


class _Peer:
    """A scripted daemon: each connection reads one request and gets the next
    reply of the current case. A refused call must not connect at all."""

    def __init__(self, path: str) -> None:
        self.replies: list[Any] = []
        self.seen: list[Any] = []
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(path)
        listener.listen()
        threading.Thread(target=self._answer, args=(listener,), daemon=True).start()

    def _answer(self, listener: socket.socket) -> None:
        while True:
            connection, _ = listener.accept()
            with connection:
                self.seen.append(json.loads(connection.makefile("rb").readline()))
                if self.replies:
                    connection.sendall((json.dumps(self.replies.pop(0)) + "\n").encode())


def _server(path: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(  # noqa: S603 - this environment's own entry point
        [str(Path(sys.executable).with_name("ai-tts-mcp"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "AI_TTS_SOCKET": path},
    )
    _exchange(
        process,
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
    )
    _exchange(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return process


def _exchange(process: subprocess.Popen[str], message: dict[str, Any]) -> Any:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline()) if "id" in message else None


def _call(process: subprocess.Popen[str], tool: str, arguments: dict[str, Any]) -> Any:
    message = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    return _exchange(process, message)


def run_cases(calls: list[tuple[str, dict[str, Any], list[Any]]]) -> list[dict[str, Any]]:
    """Run every call; one Python server serves all calls that have a peer.

    Each call completes before the next starts, so the requests the peer
    reads between two calls belong to the first. A call without replies runs
    on its own server whose socket does not exist.
    """
    peer_path = str(Path(tempfile.mkdtemp(prefix="aitts-peer-")) / "peer.sock")
    peer = _Peer(peer_path)
    shared = _server(peer_path)
    results = []
    for tool, arguments, replies in calls:
        if replies:
            peer.replies = list(replies)
            peer.seen = []
            reply = _call(shared, tool, arguments)
            seen = peer.seen
        else:
            alone = _server(ABSENT)
            reply = _call(alone, tool, arguments)
            assert alone.stdin is not None
            alone.stdin.close()
            alone.wait()
            seen = []
        results.append(
            {
                "tool": tool,
                "arguments": arguments,
                "socket": "peer" if replies else "absent",
                "daemon_replies": replies,
                "daemon_requests": seen,
                "reply": reply,
            }
        )
    assert shared.stdin is not None
    shared.stdin.close()
    shared.wait()
    return results


_RECORDED: list[dict[str, Any]] = json.loads(_CASES.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def python_results() -> list[dict[str, Any]]:
    """The Python server's results for every recorded call, in one run.

    Retire when the cases no longer share one server; each check reads only.
    """
    calls = [(c["tool"], c["arguments"], c["daemon_replies"]) for c in _RECORDED]
    return run_cases(calls)


@pytest.mark.parametrize("index", range(len(_RECORDED)), ids=[c["tool"] for c in _RECORDED])
def test_case_matches_the_python_server(index: int, python_results: list[dict[str, Any]]) -> None:
    assert python_results[index] == _RECORDED[index]


if __name__ == "__main__":
    captured = _daemon_replies()
    cases = run_cases([(tool, args, [captured[op] for op in ops]) for tool, args, ops in CALLS])
    _CASES.write_text(json.dumps(cases, indent=1) + "\n", encoding="utf-8")
