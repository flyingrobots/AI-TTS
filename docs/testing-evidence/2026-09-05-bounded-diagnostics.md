# Bounded local diagnostics evidence — 2026-09-05

Change kind: feature

Oracle: a long-running launch agent must retain enough local operational
evidence to diagnose lifecycle failures without unbounded disk growth or
turning diagnostics into a second store of speech text and file metadata

## Boundary and policy

`diagnostic_log_handler()` is the outbound filesystem adapter for persistent
daemon diagnostics. Its default policy owns exactly one 2 MiB active file and
two 2 MiB backups. It normalizes the containing directory to `0700`, each
existing generation to `0600`, refuses a symlink as the active file, and opens
every new active generation with no-follow and close-on-exec flags rather than
trusting the inherited umask. An oversized generation from the old unbounded
launchd configuration is discarded before the handler starts.

The formatter limits any one rendered record to half of a generation and
removes exception messages, tracebacks, and stack payloads. AI-TTS package log
calls use literal `event=` templates and interpolate only a reviewed allowlist
of non-content values: numeric byte counts and retry delays, the package
version, and the configured engine name. Speech text, source labels, selected
document paths, cache paths, and exception strings are excluded.

The launch-agent renderer now passes `daemon --log-file <absolute path>` and
routes launchd-managed stdout and stderr to `/dev/null`, preventing unrelated
process output from bypassing rotation. The renderer remains a standalone
stdlib script because the documented install flow invokes it outside the
separately installed uv-tool environment. Foreground daemon runs without
`--log-file` retain their existing terminal logging behavior.

## Feature falsification before implementation

The boundary tests were introduced before the production implementation. The
observed failures were specific:

- the launch-agent contract received only `[executable, "daemon"]` and still
  mapped both standard streams to the unbounded log path;
- the diagnostics test module failed collection because
  `aitts.adapters.diagnostic_logging` did not exist;
- after the first handler existed, an injected exception string appeared in
  the persisted traceback;
- running the renderer with Python `-I -S` failed with
  `ModuleNotFoundError: No module named 'aitts'`; and
- two seeded 300-byte legacy generations survived a configured 256-byte
  ceiling until explicit startup bounding was added.

These failures establish that the final results depend on the new adapter,
privacy projection, standalone distribution boundary, and migration policy.

## Probe-driven correction

The first artifact pass exposed that importing the shared private-files module
from `scripts/render_launch_agent.py` silently relied on the development
environment. The README intentionally runs that script with ordinary
`python3` after installing `ai-tts` into a separate uv-tool environment. A
stdlib-isolated subprocess test made the dependency visible. The final script
performs the small no-follow directory operation locally; the installed daemon
continues to use the package adapter for log files and rotations.

Review also caught a migration hole in `RotatingFileHandler`: it prevents
future growth, but an already oversized active file can become an oversized
backup on the first rollover. Handler construction now bounds every managed
generation before opening the active stream.

## Assertion calibration

Three independent control mutations were run and restored:

1. Multiplying the configured rotation ceiling by 100 prevented the second
   backup from appearing; the rotation test failed on the exact artifact set.
2. Restoring a path-bearing `could not purge ... %s` cache log caused the
   package diagnostic audit to report both a missing stable event code and the
   unsafe `entry.path` field.
3. Changing the default generation size from 2 MiB to 1 MiB made the default
   retention test report `1048576` rather than `2097152` bytes.

## Final verification

The restored exact tree passed:

- five focused diagnostic-handler and package-call-site tests, the two
  launch-agent distribution contracts, and the playback-supervisor logging
  regression;
- all 242 Python tests in 4.85 seconds;
- all 74 unchanged Swift tests under the repository's 60-second deadline;
- Ruff lint and format checks, strict mypy, `uv lock --check`, and
  `git diff --check`;
- `actionlint` and `zizmor 1.28.0` offline with no workflow findings;
- offline wheel and source-distribution construction, `check-wheel-contents`,
  `twine check`, and an isolated Python 3.12 wheel installation; and
- a production native app build accepted by `codesign --verify --deep
  --strict` and `plutil -lint`.

A fake daemon was also launched through the real CLI under umask `0000` with
an explicit log path. The created log directory reported mode `0700`, the
active file reported `0600`, and the retained record was the bounded static
startup event with version and fake-engine identity. The standalone renderer
produced a valid plist whose arguments include `--log-file` and whose standard
streams both resolve to `/dev/null`.

## Remaining acceptance boundary

This slice did not replace or restart the user's installed launch agent, wait
through a real 2 MiB rollover, or add a user-facing diagnostics export. It also
does not add local metrics or cross-stage correlation. Those are distinct
observability and installed-acceptance slices; no claim is made that this one
closes them.
