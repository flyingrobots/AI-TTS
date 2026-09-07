# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Where state lives, and the two environment overrides (architecture §6).

These two functions decide which database a daemon opens and which socket a
client connects to. Every test in this suite depends on the overrides working,
and nothing exercised them: a change that ignored `AI_TTS_HOME` would send a
daemon at the operator's real state directory while the suite stayed green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aitts.paths import default_home, default_socket

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("state location and environment overrides in architecture section 6"),
]

HOME_VAR = "AI_TTS_HOME"
SOCKET_VAR = "AI_TTS_SOCKET"


def test_home_defaults_under_application_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HOME_VAR, raising=False)

    home = default_home()

    assert home.is_absolute()
    assert home.parts[-2:] == ("Application Support", "ai-tts")
    assert "~" not in str(home)


def test_home_honours_its_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(HOME_VAR, str(tmp_path / "state"))

    assert default_home() == tmp_path / "state"


def test_an_empty_override_is_ignored_rather_than_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HOME_VAR, "")

    # An empty variable is an unset one, not a request to use the filesystem
    # root. Treating it as a path would put state in an unexpected place.
    assert default_home().parts[-1] == "ai-tts"


def test_a_home_override_expands_a_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOME_VAR, "~/aitts-state")

    home = default_home()

    assert home.is_absolute()
    assert "~" not in str(home)
    assert home.parts[-1] == "aitts-state"


def test_the_socket_sits_inside_the_home_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(SOCKET_VAR, raising=False)
    monkeypatch.setenv(HOME_VAR, str(tmp_path / "state"))

    # The socket follows the home override; a client and a daemon given the
    # same home must agree on where to meet.
    assert default_socket() == tmp_path / "state" / "ai-tts.sock"


def test_the_socket_honours_its_own_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_VAR, str(tmp_path / "state"))
    monkeypatch.setenv(SOCKET_VAR, str(tmp_path / "elsewhere.sock"))

    assert default_socket() == tmp_path / "elsewhere.sock"


def test_a_socket_override_expands_a_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SOCKET_VAR, "~/aitts.sock")

    socket_path = default_socket()

    assert socket_path.is_absolute()
    assert "~" not in str(socket_path)
