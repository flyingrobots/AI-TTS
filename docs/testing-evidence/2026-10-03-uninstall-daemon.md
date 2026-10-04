# Uninstall refusal preserves installed files

Change-kind: bug fix. Issue #73. Oracle: uninstall must not delete either agent plist or the CLI while launchd refuses to stop a loaded agent. An already-stopped agent need not be restarted after a later refusal.

The medium tests enter through the real `make uninstall` target with owned launchctl, uv, and uname tools. They cover loaded and unloaded successful removal plus independent menu-bar and daemon stop refusals. Success is checked against the surviving app and absent plists, registrations, and CLI; refusal is checked against a nonzero exit, the agent diagnostic, preserved plists and CLI, and the still-loaded daemon. The fixture explicitly models a Darwin host so these shell contracts can execute in Linux Docker without native launchd or app publication.

## RED

Against the unchanged Makefile from `6f28eb5c91df4c208bc843fedd64e4d90665e9ab`, `pytest tests/test_make_installation.py -k uninstall -q` produced three passes and one failure. The daemon-refusal case observed exit success, missing diagnostic, deleted plists, and deleted CLI while the daemon remained loaded. Earlier runs that failed at the macOS host guard were setup failures and are not regression evidence.

## GREEN

The same four cases pass after applying the daemon stop guard. Ruff and formatting checks pass. Type checking targets Darwin explicitly because the application has platform-conditioned branches.

## Boundaries

Tests run in the reusable Python 3.12 Docker worker using copied source, a read-only container root, two CPUs, 4 GiB RAM, a 1 GiB executable temporary filesystem, and a serialized validation lock. The reusable workspace and dependency cache remain subject to a checked 20 GiB aggregate project budget; generated test data is bounded by the temporary filesystem. No host checkout is mounted writable.

The broad Linux suite was also attempted and encountered macOS-only installation/publication and shell integration failures. That run is not claimed green. The focused uninstall contract is validated in Docker; the complete native suite remains the hosted macOS CI gate. Real launchd stop refusal is simulated, not induced against the user's installed daemon.
