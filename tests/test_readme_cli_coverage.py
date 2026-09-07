# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The README's CLI examples cover the CLI that exists.

Documentation drifts silently, and this is the drift that costs the most: a
reader who cannot find a command in the README reasonably concludes it is not
there. Several commands had been added without an example, so the README
described a smaller tool than the one installed.

Pinning it here rather than promising to remember. A new subcommand now fails
this test until it is either shown in the README or listed below as
deliberately undocumented, with the reason.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from aitts.cli import _build_parser

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the CLI usage section of README"),
]

README = Path(__file__).resolve().parents[1] / "README.md"

# Commands the README deliberately does not put in the example block, each
# because it is documented somewhere better rather than because it was missed.
DOCUMENTED_ELSEWHERE = {
    # Shown in the "run the daemon" and launch-agent sections, where the
    # reader needs the surrounding setup rather than a bare invocation.
    "daemon",
}


def subcommands(parser: argparse.ArgumentParser) -> set[str]:
    """Every subcommand the parser accepts."""
    found: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            found.update(action.choices)
    return found


def test_every_subcommand_appears_in_the_readme() -> None:
    text = README.read_text(encoding="utf-8")
    names = subcommands(_build_parser())

    assert names, "the parser should expose subcommands"
    missing = sorted(
        name
        for name in names - DOCUMENTED_ELSEWHERE
        if not re.search(rf"^ai-tts {re.escape(name)}\b", text, re.MULTILINE)
    )

    # A reader who cannot find a command in the README reasonably concludes it
    # does not exist.
    assert missing == [], f"undocumented ai-tts subcommands: {missing}"


def test_the_readme_does_not_show_a_command_that_was_removed() -> None:
    text = README.read_text(encoding="utf-8")
    names = subcommands(_build_parser())

    shown = set(re.findall(r"^ai-tts ([a-z][a-z-]*)", text, re.MULTILINE))

    # The other direction of the same drift, and the worse one: an example the
    # reader will copy and be told is an unknown command.
    assert shown - names == set()
