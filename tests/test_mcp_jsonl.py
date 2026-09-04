# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Raw MCP stdio framing contract."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("MCP 2026-07-28 stdio JSONL transport specification"),
]


async def test_mcp_stdout_is_only_one_json_object_per_line() -> None:
    """Oracle: MCP stdio requires newline-delimited JSON-RPC and forbids stdout noise."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "jsonl-contract", "version": "1"},
        },
    }
    entrypoint = Path(sys.executable).with_name("ai-tts-mcp")
    process = await asyncio.create_subprocess_exec(
        str(entrypoint),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, _stderr = await process.communicate((json.dumps(request) + "\n").encode())

    lines = stdout.decode().splitlines()
    parsed: list[dict[str, Any]] = [json.loads(line) for line in lines]
    assert process.returncode == 0
    assert stdout.endswith(b"\n")
    assert len(parsed) == 1
    assert parsed[0]["jsonrpc"] == "2.0"
    assert parsed[0]["id"] == 1
