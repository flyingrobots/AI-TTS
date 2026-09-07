# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
#
# One entry point for a clone: `make` builds, `make install` installs, and the
# install-mcp / install-skill targets wire it into local coding agents.
#
# The agent targets delegate to scripts/install-integration.sh, which takes the
# agent flags directly. Pass them through with AGENTS, or call the script.

SHELL := /bin/sh

# -- host gate ------------------------------------------------------------
# AI-TTS owns a CoreAudio output device and installs a launchd agent. Neither
# exists off macOS, so bail before any target can half-run.
UNAME_S := $(shell uname -s)
ifneq ($(UNAME_S),Darwin)
$(error AI-TTS is macOS-only; this host reports '$(UNAME_S)'. It owns a CoreAudio output device and installs a launchd user agent, neither of which exists elsewhere. Nothing was changed)
endif

# -- configuration --------------------------------------------------------
PYTHON_VERSION ?= 3.12
APP_BUNDLE     ?= $(HOME)/Applications/AI-TTS.app
DIST           ?= dist
MENUBAR        := clients/menubar
LAUNCH_AGENT   := $(HOME)/Library/LaunchAgents/com.flyingrobots.ai-tts.plist
GUI_DOMAIN     := gui/$(shell id -u)
SERVICE        := $(GUI_DOMAIN)/com.flyingrobots.ai-tts
INSTALLER      := scripts/install-integration.sh

# Agent selection for the integration targets, e.g.
#   make install-mcp AGENTS="--claude --codex"
# Empty means every agent the installer knows.
AGENTS ?=

UV := $(shell command -v uv 2>/dev/null)

.DEFAULT_GOAL := build
.PHONY: build install install-mcp install-skill install-agents install-all \
        app test test-python test-swift lint clean uninstall \
        doctor help tools

# -- build ----------------------------------------------------------------

## build: compile the menu-bar app and sync the Python environment
build: export AITTS_DIST := $(DIST)
build: tools
	@printf '==> syncing the Python environment\n'
	@uv sync --all-extras
	@printf '==> building the menu-bar app bundle into %s\n' "$$AITTS_DIST"
	@mkdir -p -- "$$AITTS_DIST"
	@uv run python scripts/build_app_bundle.py --output "$$AITTS_DIST/AI-TTS.app" --force
	@printf '\nBuilt %s\n' "$$AITTS_DIST/AI-TTS.app"
	@printf 'Install it with: make install\n'

## app: rebuild only the installed app bundle in place
app: export AITTS_APP := $(APP_BUNDLE)
app: tools
	@printf '==> rebuilding %s\n' "$$AITTS_APP"
	@uv run python scripts/build_app_bundle.py --output "$$AITTS_APP" --force
	@printf 'Quit and reopen AI-TTS to pick it up, or: open %s\n' "$$AITTS_APP"

# -- install --------------------------------------------------------------

## install: install the CLI and MCP server, the app, and the launchd agent
install: export AITTS_APP := $(APP_BUNDLE)
install: export AITTS_PLIST := $(LAUNCH_AGENT)
install: tools
	@printf '==> installing the ai-tts and ai-tts-mcp executables\n'
	@uv tool install --force --python $(PYTHON_VERSION) --with "kokoro>=0.9.4" .
	@printf '==> installing %s\n' "$$AITTS_APP"
	@uv run python scripts/build_app_bundle.py --output "$$AITTS_APP" --force
	@printf '==> installing the launchd user agent\n'
	@uv run python scripts/render_launch_agent.py \
		--executable "$$(uv tool dir --bin)/ai-tts" --force
	@launchctl bootout "$(SERVICE)" 2>/dev/null || true
	@launchctl bootstrap "$(GUI_DOMAIN)" "$$AITTS_PLIST"
	@printf '\nInstalled. The daemon is running; the menu-bar app is not.\n'
	@printf 'Start it when you want it:  open %s\n' "$$AITTS_APP"
	@printf 'Check the daemon:           make doctor\n'
	@printf 'Wire up your agents:        make install-agents\n'

## install-mcp: register the MCP server with local agents (AGENTS="--claude")
install-mcp:
	@$(INSTALLER) mcp $(AGENTS)

## install-skill: install the speak skill into local agents (AGENTS="--codex")
install-skill:
	@$(INSTALLER) skill $(AGENTS)

## install-agents: both agent integrations at once
install-agents: install-mcp install-skill

## install-all: the application and every agent integration
install-all: install install-agents

# -- checks ---------------------------------------------------------------

## test: run the Python and Swift suites
test: test-python test-swift

test-python: tools
	@uv run pytest

test-swift:
	@swift test --package-path "$(MENUBAR)"

## lint: ruff and mypy, both at the strictness this repo enforces
lint: tools
	@uv run ruff check
	@uv run ruff format --check
	@uv run mypy

## doctor: report whether the daemon is up and what is wired in
doctor:
	@printf '==> daemon\n'
	@if command -v ai-tts >/dev/null 2>&1; then \
		ai-tts status || printf '  daemon is not answering (exit %s)\n' "$$?"; \
	elif [ -x "$$(uv tool dir --bin 2>/dev/null)/ai-tts" ]; then \
		"$$(uv tool dir --bin)/ai-tts" status || true; \
	else \
		printf '  ai-tts is not installed; run: make install\n'; \
	fi
	@printf '\n==> agent integrations (nothing is changed by this)\n'
	@$(INSTALLER) mcp --all --dry-run || true
	@$(INSTALLER) skill --all --dry-run || true

# -- housekeeping ---------------------------------------------------------

## clean: remove build products, leaving anything installed alone
clean: export AITTS_DIST := $(DIST)
clean: export AITTS_MENUBAR := $(MENUBAR)
clean:
	@rm -rf -- "$$AITTS_DIST" "$$AITTS_MENUBAR/.build"
	@printf 'Removed %s and %s/.build\n' "$$AITTS_DIST" "$$AITTS_MENUBAR"

## uninstall: stop and remove the launchd agent, and the installed executables
uninstall: export AITTS_PLIST := $(LAUNCH_AGENT)
uninstall: export AITTS_APP := $(APP_BUNDLE)
uninstall:
	@printf '==> stopping and removing the launchd agent\n'
	@launchctl bootout "$(SERVICE)" 2>/dev/null || true
	@rm -f -- "$$AITTS_PLIST"
	@printf '==> removing the executables\n'
	@uv tool uninstall ai-tts 2>/dev/null || true
	@printf '\nLeft in place on purpose: %s, your speech history and\n' "$$AITTS_APP"
	@printf 'cached audio under ~/Library/Application Support/ai-tts, and any\n'
	@printf 'skill or MCP registration in your agents. Remove those by hand.\n'

tools:
ifndef UV
	$(error uv is required but was not found on PATH. Install it from https://docs.astral.sh/uv/ then re-run)
endif

## help: list these targets
help:
	@printf 'AI-TTS — a local speech daemon for macOS\n'
	@printf '\nBuild\n'
	@printf '  make                 build the menu-bar app into $(DIST)/\n'
	@printf '  make app             rebuild the installed app bundle in place\n'
	@printf '\nInstall\n'
	@printf '  make install         executables, app bundle, and launchd agent\n'
	@printf '  make install-mcp     register the MCP server with local agents\n'
	@printf '  make install-skill   install the speak skill into local agents\n'
	@printf '  make install-agents  both agent integrations\n'
	@printf '  make install-all     the application and both integrations\n'
	@printf '\nCheck\n'
	@printf '  make test            the Python and Swift suites\n'
	@printf '  make lint            ruff and mypy\n'
	@printf '  make doctor          what is running and what is wired in\n'
	@printf '\nHousekeeping\n'
	@printf '  make clean           remove build products\n'
	@printf '  make uninstall       stop and remove the daemon and executables\n'
	@printf '\nAgent selection\n'
	@printf '  make install-mcp                      every agent found\n'
	@printf '  make install-mcp AGENTS="--claude"    just one\n'
	@printf '  ./scripts/install-integration.sh skill --claude --codex\n'
	@printf '  agents: --claude  --codex  --gemini  --all   (plus --dry-run)\n'
