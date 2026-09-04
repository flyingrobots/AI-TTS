# Checkout-independent distribution evidence

Date: 2026-09-03

Change kind: bug fix

Oracle: v0.1.0 checkout-independent distribution contract

## Red on the unfixed code

Commit `5deb6cb` adds the three distribution behaviors before their adapters
exist. On that commit, pytest collection fails because
`scripts.build_app_bundle` cannot be imported. The prior launchd artifact also
contains a literal path into this checkout's `.venv`, and there is no app
bundle builder or typed-wheel marker.

## Assertion calibration

Each load-bearing assertion was then made red independently against the GREEN
implementation and restored before the final run:

1. `LSMultipleInstancesProhibited` was changed from `true` to `false`.
   `test_app_bundle_has_release_identity_without_checkout_paths` failed with
   `single_instance: False != True`.
2. direct launch arguments were replaced by `/bin/sh -c`.
   `test_launch_agent_uses_installed_executable_without_shell_expansion`
   failed on both the argument vector and `has_shell: True != False`.
3. `src/aitts/py.typed` was removed.
   `test_wheel_installs_cli_entry_points_outside_checkout` built and installed
   the wheel successfully, then failed with `typed_marker: False != True`.

The restored contract run completed with `3 passed`.

## Real artifact receipts

- `scripts/build_app_bundle.py --output <temp>/AI-TTS.app` compiled the release
  Swift target, assembled the app, and applied an ad-hoc signature.
- `codesign --verify --deep --strict <temp>/AI-TTS.app` exited successfully.
- `plutil -lint <temp>/AI-TTS.app/Contents/Info.plist` exited successfully.
- An isolated `uv tool install .` resolved and installed the `ai-tts` and
  `ai-tts-mcp` executables, and installed `ai-tts --help` ran with its working
  directory outside the checkout.

The same source install with `--offline` failed because a `sounddevice` wheel
was not present in the local cache. That is expected cache behavior, not a
claim that a fresh installation is offline-capable.

## Remaining boundary

The app is ad-hoc signed for a local source installation. It is not Developer
ID signed or notarized, and no clean external-machine install/launch journey
has yet been automated. Those are explicit release-profile blind spots rather
than properties claimed by this slice.
