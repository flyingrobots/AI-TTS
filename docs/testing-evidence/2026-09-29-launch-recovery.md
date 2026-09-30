# Installation repair and disconnected-menu recovery

## Installation repair

Change-kind: bug fix.

- `test_bundle_metadata_can_import_built_application_modules` exercises bundle
  construction with owned build products and a compiler-boundary double. Oracle:
  the App Intents compiler search directory contains the built application module.
  Size: medium. Before the fix, the Xcode product layout failed with
  `App Intents compiler cannot import built modules from .../Products/Release/Modules`;
  the native SwiftPM layout passed. Both pass after the fix.
- `test_install_includes_the_english_model_in_the_daemon_environment` inspects
  make's emitted installation command in a controlled dry run. Oracle: English
  speech's spaCy model is installed in the same uv tool environment as the daemon,
  rather than delegated to a runtime installer. Size: medium. Before the fix,
  the model URL assertion failed because the extras contained only `kokoro>=0.9.4`.
  It passes after adding the model to the tool installation.
- Real installation reproduced both faults: Xcode's module layout differed from
  the hardcoded Modules directory; spaCy's fallback `uv pip install` installed
  its model in the checkout environment, while launchd could not run that fallback.
  Model installation in the daemon environment resolved synthesis. A synthetic
  setup-check utterance reached `Played` through the installed CLI and daemon.

These tests may be deleted when the corresponding packaging path is retired.
The dry-run test checks installation intent; the real installed speech receipt
is the integration evidence, not a claim that a command projection proves speech.

## Disconnected menu

Change-kind: feature.

The disconnected view offers Launch daemon, View Logs, and Quit. Launch runs
outside the UI thread, suppresses duplicate clicks, and surfaces failures. It
uses the installed user launch agent, bootstrapping only when unregistered,
and kickstarts without killing an existing process. Logs open the local daemon
log, falling back to its directory. Quit terminates the menu application.

`DaemonLauncherTests` is medium, with an owned temporary home and injected
process boundary. Its oracle is the installed launch-agent contract and the
requested explicit launch behavior. Four cases cover registered service,
unregistered service, missing installation, and failed start. Replacing the
launch implementation with a no-op produced four named assertion failures:
two empty command lists and two missing user-facing errors. Restoring the
implementation returned all four to green. Delete these cases if explicit
launch support is removed or its OS boundary is replaced.

Validation:

- 101 Swift tests passed under the 60-second deadline after restoring the mutation.
- 18 Python distribution and Swift testing-policy tests passed.
- Targeted Ruff checks, formatting checks, mypy, and git diff whitespace check passed.
- Release bundle compiled, extracted App Intents metadata, and was signed.
- The production DaemonLauncher compiled into a temporary acceptance harness
  successfully bootstrapped the actual unregistered installed service; the CLI
  subsequently reported it reachable. The updated installed menu app was reopened.

Limits: automated tests do not click the SwiftUI buttons or verify the external
log viewer. A final reinstall hit launchd bootstrap error 5 immediately after
bootout; once teardown completed, the new launcher successfully loaded the
service. That reinstall timing race remains outside these changes. Existing
playback was paused after service restart and was not resumed by acceptance
checks; the extra queued setup-check was cancelled.
