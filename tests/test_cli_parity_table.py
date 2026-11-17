# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The shared CLI parity table still describes the Python CLI.

``tests/fixtures/cli_parity.json`` lists argument vectors with the exit
status and the request the Python CLI produces. The Rust ``ai-tts`` binary
(``crates/aitts-cli``) is tested against the same table, so this test keeps the
table tied to the reference implementation. Re-baseline: when the Python CLI
changes on purpose, update the affected rows by hand and review the diff.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from aitts import cli

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the Python ai-tts CLI argument grammar and payload builders"),
]

_TABLE = Path(__file__).parent / "fixtures" / "cli_parity.json"
_ROWS: list[dict[str, Any]] = json.loads(_TABLE.read_text(encoding="utf-8"))["rows"]


def _python_row(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []

    def accept(_client: cli.Client, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append(payload)
        return {"ok": True}

    monkeypatch.setattr(cli.Client, "request", accept)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        try:
            code = cli.main(["--socket", "/nonexistent/ai-tts.sock", *argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    row: dict[str, Any] = {"argv": argv, "exit": code}
    if sent:
        row["request"] = sent[0]
    return row


@pytest.mark.parametrize("row", _ROWS, ids=[" ".join(r["argv"]) or "<empty>" for r in _ROWS])
def test_table_row_matches_python_cli(row: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    assert _python_row(row["argv"], monkeypatch) == row
