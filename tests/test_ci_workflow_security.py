# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""CI workflow trust boundaries remain explicit and immutable."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("least-privilege and immutable GitHub Actions execution policy"),
]

REPOSITORY = Path(__file__).parents[1]
WORKFLOW = REPOSITORY / ".github" / "workflows" / "ci.yml"
ACTION_REFERENCE = re.compile(r"(?m)^\s*(?:-\s+)?uses: (?P<reference>[^\s#]+)")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _action_step_bodies(text: str, action: str) -> list[str]:
    step_pattern = re.compile(r"(?ms)^      - (?P<body>.*?)(?=^      - |\Z)")
    action_pattern = re.compile(
        rf"(?m)^(?:uses:|        uses:) {re.escape(action)}@[0-9a-f]{{40}}(?:\s|$)"
    )
    return [
        match.group("body")
        for match in step_pattern.finditer(text)
        if action_pattern.search(match.group("body"))
    ]


def test_workflow_token_is_read_only_by_default() -> None:
    assert re.search(r"(?m)^permissions:\n  contents: read$", _workflow_text())


def test_every_external_action_is_pinned_to_a_full_commit_sha() -> None:
    references = ACTION_REFERENCE.findall(_workflow_text())
    external_references = [reference for reference in references if not reference.startswith("./")]

    assert external_references
    assert [
        reference
        for reference in external_references
        if not re.search(r"@[0-9a-f]{40}$", reference)
    ] == []


def test_no_job_or_scope_requests_write_permission() -> None:
    assert not re.search(r"(?m)^\s+[a-z-]+: write$", _workflow_text())


def test_checkout_never_persists_the_workflow_token() -> None:
    bodies = _action_step_bodies(_workflow_text(), "actions/checkout")

    assert len(bodies) == 2
    assert all(re.search(r"(?m)^          persist-credentials: false$", body) for body in bodies)


def test_setup_uv_installs_the_reviewed_tool_version() -> None:
    bodies = _action_step_bodies(_workflow_text(), "astral-sh/setup-uv")

    assert len(bodies) == 1
    assert re.search(r'(?m)^          version: "0\.9\.18"$', bodies[0])


def test_project_commands_cannot_re_resolve_the_lockfile() -> None:
    commands = re.findall(r"(?m)^\s+run: (uv (?:sync|run)[^\n]+)$", _workflow_text())

    assert commands
    assert all("--frozen" in command for command in commands)
