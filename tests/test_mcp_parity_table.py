# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The MCP parity fixtures still describe the Python ``ai-tts-mcp`` server.

``tests/fixtures/mcp_session.json`` holds JSON-RPC sessions with the exact
replies of the Python server (``null`` where it sends none, detected by a
following ``ping`` probe), and
``crates/aitts-cli/src/mcp_tools.json`` holds its ``tools/list`` result. The
Rust ``ai-tts mcp`` is tested against both files, so this test ties them to the
reference server. Re-baseline: ``uv run python -m tests.test_mcp_parity_table``
rewrites the session file from the Python server; review the diff.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the Python ai-tts-mcp server over MCP stdio"),
]

_REPOSITORY = Path(__file__).parents[1]
_SESSIONS = _REPOSITORY / "tests" / "fixtures" / "mcp_session.json"
_TOOLS = _REPOSITORY / "crates" / "aitts-cli" / "src" / "mcp_tools.json"
# Sent after each message: when its reply comes first, the message got none.
# A ping changes no state, so the probe does not alter the session.
_PROBE = {"jsonrpc": "2.0", "id": "parity-probe", "method": "ping"}


def _initialize(version: str, request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "parity", "version": "1"},
        },
    }


def _request(request_id: object, method: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method}


_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}

SESSIONS: list[list[Any]] = [
    [
        _initialize("2025-11-25"),
        _INITIALIZED,
        _request(2, "ping"),
        _request(3, "tools/list"),
        _request(4, "prompts/list"),
        _request(5, "resources/list"),
        _request(6, "resources/templates/list"),
        _request(7, "bogus/method"),
        _request("s-8", "ping"),
    ],
    *[
        [_initialize(version)]
        for version in ("2024-11-05", "2025-03-26", "2025-06-18", "2026-07-28", "1999-01-01")
    ],
    [_request(1, "tools/list")],
    [_request(1, "ping")],
    ["not json", _initialize("2025-11-25", 2)],
    [{"jsonrpc": "2.0", "id": 1, "method": "initialize"}],
    [_initialize("2025-11-25"), _request(2, "tools/list")],
    [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": 7, "capabilities": {}, "clientInfo": {}},
        }
    ],
    [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {}},
        }
    ],
    [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "x", "version": "1"},
            },
        }
    ],
    [_initialize("2025-11-25"), _initialize("2025-06-18", 2)],
    [{"jsonrpc": "2.0", "method": "ping"}, _request(1, "ping")],
    [[1, 2], {"id": 1, "method": "ping"}, _request(2, "ping")],
]


def run_session(messages: list[Any]) -> dict[str, Any]:
    """Send each message to a fresh Python server and record what it answers."""
    process = subprocess.Popen(  # noqa: S603 - this environment's own entry point
        [str(Path(sys.executable).with_name("ai-tts-mcp"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "AI_TTS_SOCKET": "/nonexistent/ai-tts.sock"},
    )
    assert process.stdin is not None
    assert process.stdout is not None
    replies: list[Any] = []
    for message in messages:
        line = message if isinstance(message, str) else json.dumps(message)
        process.stdin.write(line + "\n")
        process.stdin.flush()
        if not isinstance(message, dict) or "id" in message:
            process.stdin.write(json.dumps(_PROBE) + "\n")
            process.stdin.flush()
            first = json.loads(process.stdout.readline())
            if first.get("id") == _PROBE["id"]:
                replies.append(None)
            else:
                replies.append(first)
                assert json.loads(process.stdout.readline())["id"] == _PROBE["id"]
    process.stdin.close()
    trailing = process.stdout.read()
    status = process.wait()
    assert trailing == "", f"unexpected output after the session: {trailing!r}"
    return {"messages": messages, "replies": replies, "exit": status}


_RECORDED: list[dict[str, Any]] = json.loads(_SESSIONS.read_text(encoding="utf-8"))


def _docstrings_cleaned(value: Any) -> Any:  # noqa: ANN401 - any parsed JSON value
    """Python 3.13 dedents docstrings and 3.12 does not; compare tool descriptions cleaned.

    The fixtures hold the 3.12 text, which `make install` and CI use.
    """
    if isinstance(value, dict):
        return {
            key: inspect.cleandoc(item)
            if key == "description" and isinstance(item, str)
            else _docstrings_cleaned(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_docstrings_cleaned(item) for item in value]
    return value


@pytest.mark.parametrize("index", range(len(SESSIONS)))
def test_session_replies_match_the_python_server(index: int) -> None:
    assert _docstrings_cleaned(run_session(SESSIONS[index])) == _docstrings_cleaned(
        _RECORDED[index]
    )


def test_tool_catalog_is_the_python_tools_list() -> None:
    replies = _RECORDED[0]["replies"]
    tools = next(reply for reply in replies if reply["id"] == 3)["result"]["tools"]
    assert json.loads(_TOOLS.read_text(encoding="utf-8")) == tools
    assert len(tools) == 21


if __name__ == "__main__":
    _SESSIONS.write_text(
        json.dumps([run_session(messages) for messages in SESSIONS], indent=1) + "\n",
        encoding="utf-8",
    )
