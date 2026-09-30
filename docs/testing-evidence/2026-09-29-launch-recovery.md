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

