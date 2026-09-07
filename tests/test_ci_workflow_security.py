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


# -- a tagged commit produces verified, retained release artifacts --------


def test_a_tag_triggers_the_workflow() -> None:
    text = _workflow_text()

    # Without this a release is built from whatever was last pushed to main,
    # which is not necessarily the commit the tag names.
    assert re.search(r"(?m)^  push:\n(?:.*\n)*?    tags:\n      - \"v\*\"$", text)


def test_the_release_job_only_runs_for_a_tag() -> None:
    body = _job_body("release")

    # On every other push it would rebuild what the other jobs already built.
    assert "if: startsWith(github.ref, 'refs/tags/v')" in body


def test_the_release_job_builds_every_distributed_artifact() -> None:
    body = _job_body("release")

    # What a person actually installs: the wheel and sdist for the CLI and
    # MCP server, and the signed bundle for the menu-bar app. A release
    # missing one of them is discovered by whoever tries to install it.
    required = {
        "uv build",
        "scripts/build_app_bundle.py",
        "codesign --verify",
        "actions/upload-artifact@",
        "if-no-files-found: error",
    }
    assert {fragment for fragment in required if fragment not in body} == set()


def test_the_release_job_verifies_before_it_publishes_anything() -> None:
    body = _job_body("release")

    # Artifacts built from an unverified tree are worse than no artifacts:
    # they look official.
    assert "needs: [python, supply-chain, swift]" in body


def test_the_release_job_holds_no_more_privilege_than_the_rest() -> None:
    body = _job_body("release")

    # Deliberately read-only, like every other job. Assets are retained on
    # the run rather than pushed to a GitHub Release, because attaching them
    # needs contents: write and the whole workflow's trust boundary is that
    # nothing here can write to the repository. Creating the release from
    # these verified artifacts stays a human action.
    assert not re.search(r"(?m)^\s+[a-z-]+: write$", body)


def _job_body(name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
        _workflow_text(),
    )
    assert match is not None, f"no {name} job in the workflow"
    return match.group("body")


# -- both bundle-building jobs must select an Xcode explicitly ------------


def test_every_job_that_builds_the_bundle_selects_an_xcode() -> None:
    text = _workflow_text()
    building = [
        name for name in ("swift", "release") if "scripts/build_app_bundle.py" in _job_body(name)
    ]

    assert building == ["swift", "release"]
    # The runner's default Xcode is older than the one this is developed
    # against and cannot extract App Intents metadata, so a bundle built on
    # the default would ship without Shortcuts integration — or, as happened,
    # fail the job with a message that named no cause.
    for name in building:
        assert "xcode-select -s /Applications/Xcode_" in _job_body(name), name
    del text


def test_the_selected_xcode_is_pinned_to_one_version() -> None:
    selections = set(
        re.findall(r"xcode-select -s (/Applications/Xcode[^\s]*\.app)", _workflow_text())
    )

    # Pinned for the same reason the actions are pinned to commit SHAs and uv
    # to one version: a toolchain that drifts changes the artifact. One
    # version across both jobs, so the CI bundle and the release bundle are
    # built by the same compiler.
    assert len(selections) == 1, selections
