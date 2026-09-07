#!/bin/sh
# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
#
# Install AI-TTS into a local coding agent.
#
# Skills follow the open agent-skills layout: one SKILL.md carrying `name` and
# `description` frontmatter, in a directory named after the skill. Claude Code,
# Codex and Gemini all read that same layout, so installing a skill is one file
# copied to three destinations rather than three formats to maintain.
#
# MCP registration is not portable in the same way — each host has its own
# `mcp add` spelling — so each is named explicitly below and printed by
# --dry-run so it can be run by hand on a host this script does not know.

set -eu

REPO_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
SKILL_NAME=speak
SKILL_SOURCE="$REPO_ROOT/skills/$SKILL_NAME/SKILL.md"
SERVER_NAME=ai-tts

DRY_RUN=0
SUBCOMMAND=""
WANT_CLAUDE=0
WANT_CODEX=0
WANT_GEMINI=0
SELECTED=0

usage() {
    cat <<'USAGE'
Install AI-TTS into a local coding agent.

Usage:
  install-integration.sh mcp   [agents...] [--dry-run]
  install-integration.sh skill [agents...] [--dry-run]

Subcommands:
  mcp      register the ai-tts-mcp stdio server with each agent
  skill    install the speak skill into each agent's skills directory

Agents:
  --claude    Claude Code      (~/.claude/skills,  claude mcp add)
  --codex     Codex            (~/.codex/skills,   codex mcp add)
  --gemini    Gemini CLI       (~/.gemini/skills,  gemini mcp add)
  --all       every agent above (the default when none is named)

Options:
  --dry-run   print what would happen and change nothing
  --help      show this message

An agent whose CLI is not installed is skipped rather than failing the run,
so this is safe to run on a machine with only some of them.
USAGE
}

die() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

# Overridable so the test suite never writes into a real home directory.
host_os() {
    if [ -n "${AITTS_FAKE_UNAME:-}" ]; then
        printf '%s' "$AITTS_FAKE_UNAME"
    else
        uname -s
    fi
}

require_macos() {
    os=$(host_os)
    if [ "$os" != "Darwin" ]; then
        die "AI-TTS is macOS-only; this host reports '$os'. It owns a CoreAudio
       output device and installs a launchd agent, neither of which exists
       elsewhere. Nothing was changed."
    fi
}

resolve_bin() {
    # $1 = executable name. The override is read by name rather than through
    # eval, which would expand whatever the value contained.
    case "$1" in
        ai-tts) override=${AITTS_BIN:-} ;;
        ai-tts-mcp) override=${AITTS_MCP_BIN:-} ;;
        *) override= ;;
    esac
    if [ -n "$override" ]; then
        printf '%s' "$override"
        return 0
    fi
    if command -v uv >/dev/null 2>&1; then
        candidate="$(uv tool dir --bin 2>/dev/null)/$1"
        if [ -x "$candidate" ]; then
            printf '%s' "$candidate"
            return 0
        fi
    fi
    if [ -x "$REPO_ROOT/.venv/bin/$1" ]; then
        printf '%s' "$REPO_ROOT/.venv/bin/$1"
        return 0
    fi
    resolved=$(command -v "$1" 2>/dev/null || true)
    printf '%s' "$resolved"
}

# Render a value as a single POSIX shell word. Single-quote it and close,
# escape, reopen around each embedded apostrophe, which is the only character
# single quotes cannot carry.
shell_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

skills_dir_for() {
    case "$1" in
        claude) printf '%s' "${AITTS_CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}" ;;
        codex) printf '%s' "${AITTS_CODEX_SKILLS_DIR:-$HOME/.codex/skills}" ;;
        gemini) printf '%s' "${AITTS_GEMINI_SKILLS_DIR:-$HOME/.gemini/skills}" ;;
    esac
}

# Each host spells stdio registration differently; claude and codex want the
# command after a `--` separator, gemini takes it positionally.
#
# This renders the command for a human to read or retype. It is deliberately
# not what gets executed: a path is a single argument, and building a string
# to re-split would break on any path containing a space and would run
# whatever a crafted path contained.
mcp_add_command_for() {
    quoted=$(shell_quote "$2")
    case "$1" in
        claude | codex) printf '%s mcp add %s -- %s' "$1" "$SERVER_NAME" "$quoted" ;;
        gemini) printf 'gemini mcp add %s %s' "$SERVER_NAME" "$quoted" ;;
    esac
}

# Registration, with the server path passed as exactly one argument.
run_mcp_add() {
    case "$1" in
        claude | codex) "$1" mcp add "$SERVER_NAME" -- "$2" ;;
        gemini) gemini mcp add "$SERVER_NAME" "$2" ;;
    esac
}

install_skill_for() {
    agent=$1
    destination="$(skills_dir_for "$agent")/$SKILL_NAME"
    binary=$(resolve_bin ai-tts)
    if [ -z "$binary" ]; then
        die "could not find the ai-tts executable; run 'make install' first, or
       set AITTS_BIN to its absolute path"
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  %-7s skill  -> %s/SKILL.md (dry run)\n' "$agent" "$destination"
        return 0
    fi
    mkdir -p "$destination"
    # Replace the committed placeholder with this machine's path. The skill in
    # the repository stays machine-independent; the installed copy is concrete.
    #
    # Two separate escapes, and both are needed. The skill's commands are run
    # by an agent, so the path has to be a single shell word first; that word
    # is then escaped for sed's replacement grammar, where an unescaped &
    # inserts the matched text and an unescaped | would end the expression.
    quoted=$(shell_quote "$binary")
    escaped=$(printf '%s' "$quoted" | sed -e 's/[&|\\]/\\&/g')
    sed "s|<AI_TTS_BIN>|$escaped|g" "$SKILL_SOURCE" >"$destination/SKILL.md"
    printf '  %-7s skill  -> %s/SKILL.md\n' "$agent" "$destination"
}

install_mcp_for() {
    agent=$1
    server=$(resolve_bin ai-tts-mcp)
    if [ -z "$server" ]; then
        die "could not find the ai-tts-mcp executable; run 'make install' first,
       or set AITTS_MCP_BIN to its absolute path"
    fi
    command_line=$(mcp_add_command_for "$agent" "$server")
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  %-7s mcp    -> %s (dry run)\n' "$agent" "$command_line"
        return 0
    fi
    if ! command -v "$agent" >/dev/null 2>&1; then
        printf '  %-7s mcp    -> skipped, no %s on PATH\n' "$agent" "$agent"
        return 0
    fi
    # Add first. Re-registering after an upgrade moved the binary is the normal
    # case, and only then is the existing entry removed — removing first would
    # leave the caller with no registration at all if the add went on to fail.
    if run_mcp_add "$agent" "$server" >/dev/null 2>&1; then
        printf '  %-7s mcp    -> registered %s\n' "$agent" "$SERVER_NAME"
        return 0
    fi
    "$agent" mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
    if run_mcp_add "$agent" "$server" >/dev/null 2>&1; then
        printf '  %-7s mcp    -> re-registered %s\n' "$agent" "$SERVER_NAME"
        return 0
    fi
    printf '  %-7s mcp    -> FAILED; run by hand: %s\n' "$agent" "$command_line"
    return 0
}

# -- arguments ------------------------------------------------------------

if [ "$#" -eq 0 ]; then
    usage >&2
    die "no subcommand given; expected 'mcp' or 'skill'"
fi

for argument in "$@"; do
    case "$argument" in
        --help | -h)
            usage
            exit 0
            ;;
    esac
done

SUBCOMMAND=$1
shift
case "$SUBCOMMAND" in
    mcp | skill) ;;
    *) die "unknown subcommand '$SUBCOMMAND'; expected 'mcp' or 'skill'" ;;
esac

while [ "$#" -gt 0 ]; do
    case "$1" in
        --claude)
            WANT_CLAUDE=1
            SELECTED=1
            ;;
        --codex)
            WANT_CODEX=1
            SELECTED=1
            ;;
        --gemini)
            WANT_GEMINI=1
            SELECTED=1
            ;;
        --all)
            WANT_CLAUDE=1
            WANT_CODEX=1
            WANT_GEMINI=1
            SELECTED=1
            ;;
        --dry-run) DRY_RUN=1 ;;
        *) die "unknown agent or option '$1'; see --help" ;;
    esac
    shift
done

if [ "$SELECTED" -eq 0 ]; then
    WANT_CLAUDE=1
    WANT_CODEX=1
    WANT_GEMINI=1
fi

# -- run ------------------------------------------------------------------

require_macos

if [ "$SUBCOMMAND" = "skill" ] && [ ! -f "$SKILL_SOURCE" ]; then
    die "skill source is missing at $SKILL_SOURCE"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    printf 'AI-TTS %s installation (dry run, nothing will change)\n' "$SUBCOMMAND"
else
    printf 'AI-TTS %s installation\n' "$SUBCOMMAND"
fi

for agent in claude codex gemini; do
    case "$agent" in
        claude) [ "$WANT_CLAUDE" -eq 1 ] || continue ;;
        codex) [ "$WANT_CODEX" -eq 1 ] || continue ;;
        gemini) [ "$WANT_GEMINI" -eq 1 ] || continue ;;
    esac
    if [ "$SUBCOMMAND" = "skill" ]; then
        install_skill_for "$agent"
    else
        install_mcp_for "$agent"
    fi
done

if [ "$DRY_RUN" -eq 0 ] && [ "$SUBCOMMAND" = "skill" ]; then
    printf 'Start a new agent session; skills are discovered at startup.\n'
fi
