# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Where the daemon keeps its state (architecture.md §6)."""

from __future__ import annotations

import os
from pathlib import Path


def default_home() -> Path:
    """Return the daemon's home directory, honouring ``AI_TTS_HOME``."""
    override = os.environ.get("AI_TTS_HOME")
    if override:
        return Path(override).expanduser()
    return Path("~/Library/Application Support/ai-tts").expanduser()


def default_socket() -> Path:
    """Return the IPC socket path, honouring ``AI_TTS_SOCKET``."""
    override = os.environ.get("AI_TTS_SOCKET")
    if override:
        return Path(override).expanduser()
    return default_home() / "ai-tts.sock"
