# Independent menu-bar startup and recovery

Change-kind: behavior change. Installation now starts the menu-bar app and
registers it independently for login startup and abnormal-exit recovery. Normal
Quit leaves the UI closed, and reopening the installed app hands ownership back
to launchd. The daemon remains independent. Uninstall removes both registrations.

## Contract and falsification evidence

`tests/test_make_installation.py` enters through the real Make entrypoints with
owned uv, launchctl, and osascript tools and temporary installation destinations.
The oracle is the documented installation output and parsed launchd plists.
It is medium. `tests/test_launch_agent_activation.py` controls the process and
timing boundary and checks the previous artifact/registration under seeded
interrupts and launchd EIO; it is small. `MenuBarLaunchAgentTests` uses an owned
temporary home and controlled launchctl results; it is medium, with the installed
startup/standalone-launch policy as its oracle. Retire these assertions when
that installation/ownership policy is removed or superseded by a stronger check.

The [calibration receipt](2026-10-01-menu-bar-startup-calibration.json) retains
named failed checks for faults in label, executable, login startup, successful
exit policy, session, managed marker, registration, rollback, uninstall,
handoff, recursion prevention, development isolation, and standalone fallback.
The changed registration message was also falsified. Local complete red logs
are under `.git/codex-scratch/menu-bar-startup-*-red.log`.

Two pre-existing installer defects were encountered during actual installation:
uv selected Transformers 4.12.2 / tokenizers 0.10.3, whose Rust source build failed;
launchd returned EIO when bootstrap followed bootout before teardown settled.
New regressions were observed red on the installer without either correction:
`.git/codex-scratch/menu-bar-startup-install-reliability-red.log`. The installer
now selects `transformers>=4.46,<5` for Kokoro and retries only bootstrap EIO for
at most six seconds. Other errors retain immediate failure and rollback.
These corrections are prerequisites for this machine's working installation.

## Installed acceptance

The [live receipt](2026-10-01-menu-bar-startup-live.json) records two forced UI
exits, intentional Quit observed closed for twelve seconds (beyond the ten-second
launchd throttle), and manual reopen returning the UI to the registered service.
The daemon PID stays unchanged during all four observations and answers status.
The run finished with the UI running. The normal `make install` then completed
successfully with both registrations active, exercising the corrected installer
without environment overrides. Local receipt:
`.git/codex-scratch/menu-bar-startup-install-final.log`.

The current installed bundle contains the Playback setting “Lower other apps
during speech”; the daemon exposes `ducking_enabled: true`. Kokoro, the English
spaCy model, and Transformers' `AlbertModel` imported successfully in the installed
uv environment. This supersedes the old app bundle that predated the ducking work.
It does not add physical-device or permission-interaction ducking acceptance;
those limits remain in the September 30 ducking receipt.

A real logout/reboot was not performed. Login configuration is checked through
the Aqua `RunAtLoad` plist and actual launchd bootstrap. Owned launchctl tools
exercise registration outcomes; the installed observations establish this host's
real lifecycle semantics, not every macOS release.

## Validation

- Full Python suite after installer corrections: 927 passed in 22.04 seconds;
  small 0.69 seconds / 10-second budget, medium 20.70 seconds / 45-second budget.
- Full Swift suite, warnings as errors, under the sixty-second deadline: 145 passed.
- Ruff checks/format and strict mypy: passed.
- Full installation boundary subset after corrections: 40 passed.
- Plain `make install`: passed; both daemon and menu bar running afterward.

Green logs are `.git/codex-scratch/menu-bar-startup-{python,swift,lint,installation}-green.log`.

## Audit fixes

Change-kind: bug fix. The installer sent `quit` to a running menu app and bootstrapped the menu-bar agent at once. The agent's `RunAtLoad` instance could then find the old process still holding `SingleInstanceLock` and return with exit 0, which `KeepAlive {SuccessfulExit: false}` treats as an intentional Quit, so the menu bar stayed closed after a successful install. The installer now polls `application id … is running` up to 100 times, 0.1 seconds apart, and fails the install if the old UI has not exited.

`test_install_waits_for_the_quit_menu_bar_to_exit_before_registering_it` is medium and enters through `make install`. Its owned osascript keeps an incumbent alive for two probes after quit, and its owned launchctl records `lock-lost` if the menu-bar bootstrap happens while the incumbent is alive. The oracle is the single-instance lock contract in `clients/menubar/Sources/AITTSMenuBar/main.swift`. It failed on parent `9081f2d` with `AssertionError: assert 'lock-lost' == 'running'`.
