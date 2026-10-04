# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Run one command under a hard wall-clock deadline, preserving its exit status."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

_TERMINATION_GRACE_SECONDS = 2.0
_TIMEOUT_EXIT = 124
_USAGE_EXIT = 2
_MINIMUM_ARGUMENTS = 2


def _zombie_only_group(pgid: int) -> bool:
    """Confirm Darwin's EPERM is an exited group, without reaping its identity anchor."""
    result = subprocess.run(
        ["/bin/ps", "-axo", "pgid=,stat="],
        capture_output=True,
        text=True,
        check=True,
        timeout=1,
    )
    states = []
    for line in result.stdout.splitlines():
        group, state = line.split()
        if group == str(pgid):
            states.append(state)
    return bool(states) and all(state.startswith("Z") for state in states)


def _signal_owned_group(pgid: int, sig: int) -> bool:
    """Signal the still-anchored group; only verified absence of live work is benign."""
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Darwin excludes zombies from killpg's permission/success count.
        if sys.platform == "darwin" and _zombie_only_group(pgid):
            return False
        raise
    return True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the owned child process group, escalating only after a grace period."""
    if _signal_owned_group(process.pid, signal.SIGTERM):
        # Keep the unreaped leader as an identity anchor until the last group signal.
        # Reaping early could let an unrelated group reuse its numeric identifier.
        time.sleep(_TERMINATION_GRACE_SECONDS)
        _signal_owned_group(process.pid, signal.SIGKILL)
    process.wait()


def main(argv: list[str] | None = None) -> int:
    """Run COMMAND with DEADLINE_SECONDS and return its exact exit status or 124."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < _MINIMUM_ARGUMENTS:
        sys.stderr.write("usage: run_with_deadline.py DEADLINE_SECONDS COMMAND [ARG ...]\n")
        return _USAGE_EXIT
    try:
        deadline = float(args[0])
    except ValueError:
        sys.stderr.write(f"invalid deadline: {args[0]!r}\n")
        return _USAGE_EXIT
    if deadline <= 0:
        sys.stderr.write("deadline must be greater than zero\n")
        return _USAGE_EXIT

    command = args[1:]
    process = subprocess.Popen(command, start_new_session=True)  # noqa: S603
    try:
        return process.wait(timeout=deadline)
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"suite latency budget exceeded: command ran longer than {deadline:g}s\n")
        _terminate_process_group(process)
        return _TIMEOUT_EXIT


if __name__ == "__main__":  # pragma: no cover - executable wrapper
    raise SystemExit(main())
