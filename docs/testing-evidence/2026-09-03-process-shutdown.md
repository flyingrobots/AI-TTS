# Process-shutdown evidence — 2026-09-03

Change kind: bug fix.

Oracle: a launch-agent SIGTERM completes promptly once the daemon has closed
its Unix socket and SQLite store. A non-cooperative native engine call does not
own process lifetime.

## Red on the unfixed parent

Commit `9cf1b11` adds a process-boundary regression using a fake engine whose
warmup blocks for 30 seconds. On its parent, `uv run pytest
tests/test_process_lifecycle.py -q` observed the socket ready, sent SIGTERM,
waited two seconds, and then had to kill the still-live owned process group.
The assertion failed with `exited_promptly: false` and `returncode: -9`.

The test is also its assertion calibration: removing the final
`ProcessTerminationPort` call recreates the exact red result above. The process
fixture owns a fresh home and short socket directory and always reaps its exact
child process group, including on failure.
