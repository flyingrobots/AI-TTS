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
    text = _workflow_text()
    references = [
        reference
        for reference in ACTION_REFERENCE.findall(text)
        if reference.startswith("actions/checkout@")
    ]
    bodies = _action_step_bodies(text, "actions/checkout")

    assert references
    assert len(bodies) == len(references)
    assert all(re.search(r"(?m)^          persist-credentials: false$", body) for body in bodies)


def test_setup_uv_installs_the_reviewed_tool_version() -> None:
    text = _workflow_text()
    references = [
        reference
        for reference in ACTION_REFERENCE.findall(text)
        if reference.startswith("astral-sh/setup-uv@")
    ]
    bodies = _action_step_bodies(text, "astral-sh/setup-uv")

    assert references
    assert len(bodies) == len(references)
    assert all(re.search(r'(?m)^          version: "0\.9\.18"$', body) for body in bodies)


def test_project_commands_cannot_re_resolve_the_lockfile() -> None:
    commands = re.findall(r"(?m)^\s+run: (uv (?:export|sync|run)[^\n]+)$", _workflow_text())

    assert commands
    assert all("--frozen" in command for command in commands)


def test_supply_chain_job_audits_and_retains_the_full_optional_graph() -> None:
    match = re.search(
        r"(?ms)^  supply-chain:\n(?P<body>.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
        _workflow_text(),
    )

    assert match
    body = match.group("body")
    required_fragments = {
        "--all-extras",
        "--no-dev",
        "--require-hashes",
        "--strict",
        "--disable-pip",
        "--vulnerability-service pypi",
        "--format cyclonedx1.5",
        "--with-system",
        "verify_supply_chain_evidence.py",
        "actions/upload-artifact@",
        "retention-days: 14",
        "if: always()",
    }
    assert {fragment for fragment in required_fragments if fragment not in body} == set()
