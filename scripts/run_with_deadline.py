# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Run one command under a hard wall-clock deadline, preserving its exit status."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

_TERMINATION_GRACE_SECONDS = 2.0
_TIMEOUT_EXIT = 124
_USAGE_EXIT = 2
_MINIMUM_ARGUMENTS = 2


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the owned child process group, escalating only after a grace period."""
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
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
