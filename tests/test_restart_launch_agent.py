# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Reinstalling replaces the launch agent without racing launchd's teardown.

`launchctl bootout` returns before launchd has finished removing the service.
Bootstrapping the same label in that window fails with error 5 (Input/output
error), which made `make install` fail after every successful build. The
restart script must wait until the old service is gone, and give up with a
clear message, rather than hang, if it never goes.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "launchd's observed contract: bootout returns before teardown completes, "
        "and bootstrap fails with error 5 while the old service is still loaded"
    ),
]

REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "restart-launch-agent.sh"
SERVICE = "gui/501/com.flyingrobots.ai-tts"
DOMAIN = "gui/501"

# A stand-in for launchctl that models the race: after bootout the service
# stays loaded for TEARDOWN more `print` queries, and bootstrap fails with
# launchd's error 5 until it is gone.
FAKE_LAUNCHCTL = """#!/bin/sh
state="$FAKE_LAUNCHD_STATE"
remaining=$(cat "$state/remaining")
printf '%s\\n' "$*" >> "$state/calls"
case "$1" in
    bootout) cat "$state/teardown" > "$state/remaining" ;;
    print)
        if [ "$remaining" -gt 0 ]; then
            echo $((remaining - 1)) > "$state/remaining"
            exit 0
        fi
        exit 113 ;;
    bootstrap)
        if [ "$remaining" -gt 0 ]; then
            echo 'Bootstrap failed: 5: Input/output error' >&2
            exit 5
        fi
        echo loaded > "$state/bootstrapped" ;;
esac
"""


def restart(
    tmp_path: Path, *, teardown: int, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the restart script against a fake launchd that lingers ``teardown`` polls."""
    state = tmp_path / "launchd"
    state.mkdir()
    (state / "remaining").write_text("0\n")
    (state / "teardown").write_text(f"{teardown}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "launchctl"
    fake.write_text(FAKE_LAUNCHCTL)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(  # noqa: S603 - fixed script path, test-controlled args
        [str(SCRIPT), SERVICE, DOMAIN, str(tmp_path / "agent.plist")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FAKE_LAUNCHD_STATE": str(state),
            **(env or {}),
        },
        check=False,
        timeout=30,
    )
    return result, state


def test_restart_waits_for_the_old_service_to_leave_before_bootstrapping(
    tmp_path: Path,
) -> None:
    result, state = restart(tmp_path, teardown=3)

    assert result.returncode == 0, result.stderr
    assert (state / "bootstrapped").exists()


def test_restart_gives_up_with_a_reason_when_the_old_service_never_leaves(
    tmp_path: Path,
) -> None:
    result, state = restart(tmp_path, teardown=1_000, env={"AITTS_LAUNCHD_TEARDOWN_POLLS": "3"})

    assert result.returncode != 0
    assert SERVICE in result.stderr
    assert not (state / "bootstrapped").exists()
    # Bounded: it stopped polling instead of hanging, and never tried a
    # bootstrap that launchd would have refused.
    calls = (state / "calls").read_text().splitlines()
    assert sum(call.startswith("print") for call in calls) <= 4
    assert not any(call.startswith("bootstrap") for call in calls)
