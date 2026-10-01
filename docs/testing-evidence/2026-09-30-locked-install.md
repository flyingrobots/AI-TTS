# Locked, fresh tool install and launchd teardown wait

Change-kind: bug fix (three faults, all in `make install`, now implemented in `scripts/install_application.py`).

This fix first landed against the Makefile recipe. `main` then replaced that recipe with `scripts/install_application.py`, which still had all three faults, so the fixes were re-done there against its own install harness.

## Unlocked tool install

`uv tool install` ignores `uv.lock`. After huggingface-hub 2.0.0 was published, a fresh resolve of `kokoro>=0.9.4` picked huggingface-hub 2.0.0 and backtracked transformers to 4.12.2, the last release without a `huggingface-hub<2` cap. That release's tokenizers 0.10.3 fails its Rust build, so `make install` failed before installing anything. Running `uv pip compile` on `kokoro>=0.9.4` alone reproduced the selection, while the lock holds transformers 5.16.1, tokenizers 0.23.1, and huggingface-hub 1.29.0.

The installer now exports the frozen lock (`--no-dev --no-hashes --no-emit-project --extra kokoro`) into its staging directory and passes it to `uv tool install --constraints`.

- `test_install_resolves_the_daemon_environment_to_the_locked_versions` (medium, tests/test_make_installation.py) runs the real Make entry point with owned tools. The fake `uv` delegates `export` to the real uv against the real lockfile and records the constraints the tool install received. Kokoro, transformers, tokenizers, and huggingface-hub must each be pinned to a locked version. Oracle: uv.lock is the tested runtime graph.
  - On `main`'s installer it failed: `the tool install resolves without the lockfile`.
  - Mutation: exporting the mlx extra instead of kokoro failed it.

## Stale cached build

uv caches its build of a local package keyed on metadata, not sources. With the version unchanged at 0.1.0, a reinstall reported success while the daemon kept running the previous code. This was observed on the real host on 2026-09-30: the installed `playback.py` lacked the change just committed until `--reinstall-package ai-tts` was added. The tool install now always passes `--reinstall-package ai-tts`.

- `test_install_rebuilds_the_checkout_instead_of_reusing_a_cached_build` (medium) requires that argument. Oracle: `make install` installs this checkout's code.
  - On `main`'s installer it failed: `uv may install a stale cached build`.
  - Mutation: removing the argument failed it.
  - The owned harness cannot model uv's cache. The host observation above is the behavioral evidence.

## Launchd teardown race

`launchctl bootout` returns before launchd has removed the service, and the immediate `bootstrap` failed with `Bootstrap failed: 5: Input/output error`. This was seen twice on the real host on 2026-09-30, and the 2026-09-29 launch-recovery receipt records it as an open limit. `activate_launch_agent` now polls `launchctl print` every 0.1 s, up to 100 times, until the label has gone, and only then bootstraps. If the label never leaves, it raises `LaunchdTeardownTimeoutError` naming the service, and the existing rollback restores the previous plist. The rollback path waits the same way after booting out a replacement, before deciding whether to reload the incumbent.

- `test_install_waits_for_launchd_to_release_the_previous_service` (medium): the fake launchctl keeps a booted-out service visible for three `print` queries and refuses bootstrap with error 5 until then. On `main`'s installer it failed with exit status 5. With the fix, the new plist loads.
- `test_activation_gives_up_and_restores_when_the_old_service_never_leaves` (small): a service that never leaves causes a bounded failure naming the service, no bootstrap attempt, and the previous plist restored. On `main`'s installer it failed, because there was no wait to bound.
- `test_rollback_reloads_the_prior_service_after_a_lingering_teardown` (small): the bootstrap is interrupted after loading the replacement, and the rollback's bootout lingers. The incumbent must still be reloaded.
- Mutations: removing the pre-bootstrap wait failed the first two tests, and removing the rollback wait failed the third.

## Validation

- Full Python suite at the merge head: 260 small and 476 medium tests passed. `make lint` (ruff check, ruff format, mypy) is clean.
- Real host on 2026-10-01: `make install` rebuilt `ai-tts` from the checkout, installed huggingface-hub 1.29.0, tokenizers 0.23.1, and transformers 5.16.1 (the locked versions), and bootstrapped the agent on the first attempt. `ai-tts status` then reported `ok`.

Limits: the fake launchctl models the race but not launchd's internal timing. CI does not perform a networked tool install. Retire these tests if installation leaves uv tool or launchd.
