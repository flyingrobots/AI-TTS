# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""One command installs the agent integrations (README "Install for agents").

A clone should reach a working integration without reading the README twice.
`make install-mcp` and `make install-skill` delegate here, and this script
takes the agent flags directly so it works with no make at all.

Skills follow the open agent-skills layout — one `SKILL.md` with `name` and
`description` frontmatter in its own directory — which Claude Code, Codex and
Gemini all read. That is why installing a skill is the same file copied to
three destinations rather than three formats.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "the agent installation contract in README, and the open agent-skills "
        "SKILL.md layout shared by Claude Code, Codex and Gemini"
    ),
]

REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "install-integration.sh"
SKILL_SOURCE = REPO / "skills" / "speak" / "SKILL.md"
AGENTS = ("claude", "codex", "gemini")


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, str]:
    """Point every destination at a temp directory, never the real home."""
    env = dict(os.environ)
    env["AITTS_BIN"] = str(tmp_path / "bin" / "ai-tts")
    env["AITTS_MCP_BIN"] = str(tmp_path / "bin" / "ai-tts-mcp")
    for agent in AGENTS:
        root = tmp_path / agent / "skills"
        env[f"AITTS_{agent.upper()}_SKILLS_DIR"] = str(root)
    return env


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the installer with ``args``."""
    return subprocess.run(  # noqa: S603 - fixed script path, test-controlled args
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# -- the contract ---------------------------------------------------------


def test_the_installer_is_executable_and_self_documenting() -> None:
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)

    result = subprocess.run(  # noqa: S603 - fixed script path
        [str(SCRIPT), "--help"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    for expected in ("mcp", "skill", "--claude", "--codex", "--gemini", "--all"):
        assert expected in result.stdout


def test_an_unknown_subcommand_is_refused(sandbox: dict[str, str]) -> None:
    result = run(sandbox, "sing", "--claude")

    assert result.returncode != 0
    assert "sing" in result.stderr


def test_an_unknown_agent_is_refused(sandbox: dict[str, str]) -> None:
    result = run(sandbox, "skill", "--emacs")

    assert result.returncode != 0
    assert "--emacs" in result.stderr


def test_no_subcommand_is_refused(sandbox: dict[str, str]) -> None:
    result = run(sandbox)

    assert result.returncode != 0


# -- installing a skill ---------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
def test_a_skill_installs_for_one_named_agent(sandbox: dict[str, str], agent: str) -> None:
    result = run(sandbox, "skill", f"--{agent}")

    assert result.returncode == 0, result.stderr
    installed = Path(sandbox[f"AITTS_{agent.upper()}_SKILLS_DIR"]) / "speak" / "SKILL.md"
    assert installed.exists()
    # The others are untouched: naming one agent installs for exactly one.
    for other in AGENTS:
        if other != agent:
            other_path = Path(sandbox[f"AITTS_{other.upper()}_SKILLS_DIR"]) / "speak" / "SKILL.md"
            assert not other_path.exists()


def test_all_installs_the_skill_everywhere(sandbox: dict[str, str]) -> None:
    result = run(sandbox, "skill", "--all")

    assert result.returncode == 0, result.stderr
    for agent in AGENTS:
        path = Path(sandbox[f"AITTS_{agent.upper()}_SKILLS_DIR"]) / "speak" / "SKILL.md"
        assert path.exists()


def test_the_installed_skill_names_a_real_executable(sandbox: dict[str, str]) -> None:
    run(sandbox, "skill", "--claude")

    installed = Path(sandbox["AITTS_CLAUDE_SKILLS_DIR"]) / "speak" / "SKILL.md"
    body = installed.read_text(encoding="utf-8")

    # The committed skill carries a placeholder so it is machine-independent;
    # an installed copy has to name the binary on *this* machine or the first
    # command an agent runs will fail.
    assert "<AI_TTS_BIN>" not in body
    assert sandbox["AITTS_BIN"] in body
    # Frontmatter must survive substitution or no agent will load it.
    assert body.startswith("---\n")
    assert "name: speak" in body


def test_installing_a_skill_twice_replaces_rather_than_duplicates(
    sandbox: dict[str, str],
) -> None:
    installed = Path(sandbox["AITTS_CLAUDE_SKILLS_DIR"]) / "speak" / "SKILL.md"
    run(sandbox, "skill", "--claude")
    first = installed.read_text(encoding="utf-8")
    installed.write_text(first + "\nlocal edit\n", encoding="utf-8")

    result = run(sandbox, "skill", "--claude")

    assert result.returncode == 0
    assert installed.read_text(encoding="utf-8") == first


# -- dry runs and safety --------------------------------------------------


def test_a_dry_run_changes_nothing(sandbox: dict[str, str]) -> None:
    result = run(sandbox, "skill", "--all", "--dry-run")

    assert result.returncode == 0
    assert "dry run" in result.stdout.lower()
    for agent in AGENTS:
        path = Path(sandbox[f"AITTS_{agent.upper()}_SKILLS_DIR"]) / "speak" / "SKILL.md"
        assert not path.exists()


def test_mcp_registration_is_reported_per_agent(sandbox: dict[str, str]) -> None:
    result = run(sandbox, "mcp", "--all", "--dry-run")

    assert result.returncode == 0
    # Each agent's own command form is named, so a reader can run it by hand.
    assert "claude mcp add" in result.stdout
    assert "codex mcp add" in result.stdout
    assert "gemini mcp add" in result.stdout


def test_a_missing_agent_is_skipped_not_fatal(sandbox: dict[str, str]) -> None:
    # System tools present, but no agent CLI on PATH — the state of a clone on
    # a machine that has only some of these agents installed.
    env = dict(sandbox)
    env["PATH"] = "/usr/bin:/bin"

    result = run(env, "mcp", "--all")

    # Nothing installed, but a clone missing one agent must not fail the run.
    assert result.returncode == 0
    assert "skip" in result.stdout.lower()


@pytest.mark.skipif(sys.platform != "darwin", reason="the bail is macOS-specific")
def test_the_installer_refuses_a_non_macos_host(sandbox: dict[str, str]) -> None:
    env = dict(sandbox)
    env["AITTS_FAKE_UNAME"] = "Linux"

    result = run(env, "skill", "--claude")

    assert result.returncode != 0
    assert "macos" in result.stderr.lower()


def test_the_committed_skill_keeps_its_placeholder() -> None:
    body = SKILL_SOURCE.read_text(encoding="utf-8")

    # If a real path were ever committed here the repository would carry one
    # machine's layout again, which is what the placeholder exists to prevent.
    assert "<AI_TTS_BIN>" in body
    assert "/Users/" not in body


# -- paths that are legal but awkward -------------------------------------


@pytest.mark.parametrize(
    "directory",
    ["dir with spaces", "dir&ampersand", "dir'quote"],
)
def test_a_skill_installs_under_an_awkward_path(tmp_path: Path, directory: str) -> None:
    # macOS paths routinely contain spaces, and sed's replacement grammar
    # treats & as "the matched text". Building a command string and re-splitting
    # it, or substituting without escaping, corrupts both.
    binary = tmp_path / directory / "bin" / "ai-tts"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    env = dict(os.environ)
    env["AITTS_BIN"] = str(binary)
    env["AITTS_CLAUDE_SKILLS_DIR"] = str(tmp_path / "skills")

    result = run(env, "skill", "--claude")

    assert result.returncode == 0, result.stderr
    body = (tmp_path / "skills" / "speak" / "SKILL.md").read_text(encoding="utf-8")
    assert "<AI_TTS_BIN>" not in body
    # The path is shell-quoted, so it is not a bare substring once it contains
    # an apostrophe; what matters is that it parses back to the executable.
    assert any(str(binary) in shell_words(line) for line in fenced_commands(body))


def test_the_rendered_mcp_command_quotes_the_server_path(tmp_path: Path) -> None:
    server = tmp_path / "dir with spaces" / "ai-tts-mcp"
    server.parent.mkdir(parents=True)
    server.write_text("#!/bin/sh\n", encoding="utf-8")
    env = dict(os.environ)
    env["AITTS_MCP_BIN"] = str(server)

    result = run(env, "mcp", "--claude", "--dry-run")

    assert result.returncode == 0
    # Printed for a human to retype, so the path must be quoted or they will
    # paste something that splits into three arguments.
    assert f"'{server}'" in result.stdout


def fenced_commands(body: str) -> list[str]:
    """Every command line inside a fenced block, joined across continuations."""
    lines: list[str] = []
    inside = False
    pending = ""
    for line in body.splitlines():
        if line.startswith("```"):
            inside = not inside
            continue
        if not inside or not line.strip() or line.lstrip().startswith("#"):
            continue
        pending += line.rstrip("\\")
        if line.rstrip().endswith("\\"):
            continue
        lines.append(pending.strip())
        pending = ""
    return lines


def shell_words(command: str) -> list[str]:
    """Split ``command`` the way a POSIX shell would."""
    import shlex  # noqa: PLC0415 - only this check needs it

    return shlex.split(command)


@pytest.mark.parametrize("directory", ["dir with spaces", "dir&ampersand", "dir'quote"])
def test_the_installed_skill_is_runnable_under_an_awkward_path(
    tmp_path: Path, directory: str
) -> None:
    binary = tmp_path / directory / "bin" / "ai-tts"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    env = dict(os.environ)
    env["AITTS_BIN"] = str(binary)
    env["AITTS_CLAUDE_SKILLS_DIR"] = str(tmp_path / "skills")

    run(env, "skill", "--claude")

    body = (tmp_path / "skills" / "speak" / "SKILL.md").read_text(encoding="utf-8")
    # Preserving the path's text is not enough: an agent reads these commands
    # and runs them. Unquoted, `/Users/Jane Doe/bin/ai-tts say ...` executes
    # /Users/Jane, and a path containing & becomes a shell operator.
    commands = [line for line in fenced_commands(body) if "ai-tts" in line]
    assert commands, "the installed skill should contain a runnable command"
    for command in commands:
        words = shell_words(command)
        assert words[0] == str(binary), f"first word is not the executable: {words[0]!r}"


def test_the_rendered_mcp_command_survives_an_apostrophe(tmp_path: Path) -> None:
    server = tmp_path / "O'Brien" / "ai-tts-mcp"
    server.parent.mkdir(parents=True)
    server.write_text("#!/bin/sh\n", encoding="utf-8")
    env = dict(os.environ)
    env["AITTS_MCP_BIN"] = str(server)

    result = run(env, "mcp", "--claude", "--dry-run")

    assert result.returncode == 0
    printed = next(line for line in result.stdout.splitlines() if "mcp add" in line)
    command = printed.split("-> ", 1)[1].removesuffix(" (dry run)")
    # Wrapping in single quotes without escaping embedded apostrophes makes the
    # printed command unpasteable.
    assert shell_words(command)[-1] == str(server)
