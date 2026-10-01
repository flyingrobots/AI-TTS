# Locked tool install and launchd restart race

Change-kind: bug fix (two faults, both in `make install`).

## Unlocked tool install

`uv tool install` ignores `uv.lock`. After huggingface-hub 2.0.0 was published, a fresh resolve of `kokoro>=0.9.4` chose huggingface-hub 2.0.0 and backtracked transformers to 4.12.2, the last release without a `huggingface-hub<2` cap. Its tokenizers 0.10.3 failed its Rust build, so `make install` failed before installing anything. `uv pip compile` against `kokoro>=0.9.4` alone reproduced the selection (`transformers==4.12.2`, `tokenizers==0.10.3`, `huggingface-hub==2.0.0`), while the lock holds transformers 5.16.1, tokenizers 0.23.1, and huggingface-hub 1.29.0.

`make install` now exports the frozen lock (`--no-dev --no-hashes --no-emit-project --extra kokoro`) to `$(DIST)/install-constraints.txt` and passes it to `uv tool install --constraints`.

- `test_install_resolves_the_daemon_environment_to_the_locked_versions` (tests/test_distribution.py) reads the commands from a controlled `make -n install`, requires the tool install to take the exported file as `--constraints`, and then runs the projected `uv export` against the real lockfile into a temporary path. Oracle: uv.lock is the tested runtime graph. Kokoro, transformers, tokenizers, and huggingface-hub must each be pinned to a locked version. Size: medium.
- On the unfixed Makefile it failed with `the tool install resolves without the lockfile`. After the fix it passes.
- Mutation: dropping `--extra kokoro` from the export failed with `kokoro is not constrained`. Restored and green.
- Real installation: `make install` installed the executables with transformers 5.16.1.

## Launchd restart race

`launchctl bootout` returns before launchd has removed the service. The immediate `bootstrap` then failed with `Bootstrap failed: 5: Input/output error`. This was seen twice on the real host today, and the 2026-09-29 launch-recovery receipt recorded it as an open limit. The restart now lives in `scripts/restart-launch-agent.sh`. It polls `launchctl print` every 0.1 s until the label is gone, then bootstraps. It gives up with a message naming the service after `AITTS_LAUNCHD_TEARDOWN_POLLS` polls (default 100).

- `tests/test_restart_launch_agent.py` runs the script against a PATH-injected fake `launchctl`. The fake keeps the service loaded for a set number of `print` queries after bootout and refuses bootstrap with error 5 until then. Oracle: launchd's observed bootout/bootstrap behavior. Size: medium.
  - `test_restart_waits_for_the_old_service_to_leave_before_bootstrapping`: on the unfixed script (moved verbatim from the Makefile), the result was exit 5 with `Bootstrap failed: 5: Input/output error`.
  - `test_restart_gives_up_with_a_reason_when_the_old_service_never_leaves`: on the unfixed script, stderr lacked the service name. With the fix, both tests pass. The give-up case makes at most four `print` calls and no bootstrap.
- Real installation: after the fix, `make install` completed end to end, and `ai-tts status` reported `ok` with the 13 Ready items and the paused state preserved.

## Validation

- Full Python suite: 239 small and 460 medium tests passed. `make lint` (ruff check, ruff format, mypy) and shellcheck were clean.

Limits: the fake launchctl models the race; it does not reproduce launchd's internal timing. The lock test proves installation intent plus a real export. It does not perform a networked tool install in CI. Delete these tests if installation stops going through `uv tool install` or launchd.
