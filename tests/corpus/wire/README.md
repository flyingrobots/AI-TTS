# External daemon contract

Run the socket contract from the repository root:

```sh
uv run pytest -m socket_contract
```

The default command starts the real Python daemon in a separate process. Its
test adapter uses a fake synthesis engine, a fake audio sink, and fake input
activity. It needs no running service, model download, microphone, or speaker.

Set `AI_TTS_DAEMON_CMD` to select another command. The fixture parses this value
as shell-style arguments and starts the executable directly, without a shell.
Quote arguments that contain spaces. A relative executable path resolves from
the repository root. Other file arguments must be absolute because the child
working directory is a new temporary directory. The command must stay in the
foreground and serve the socket named by `AI_TTS_SOCKET`. It must put its state
under `AI_TTS_HOME` and use the same deterministic test ports: engine `fake`,
voices `bm_daniel` and `af_bella`, 100 ms synthesis, and automatic fake playback.
The reference command is the current Python interpreter followed by the
absolute path to `tests/fixture_daemon.py`.

Each test gets separate state and socket directories. The fixture supplies an
isolated `HOME`, `TMPDIR`, and XDG paths. The child receives `PATH` and the test
source path, but no inherited service or credential configuration. Startup has
a three-second deadline. The fixture retains at most 64 KiB of combined output
and monitors its state directory for a 64 MiB or 4,096-file limit. These are
test harness limits, not an operating-system sandbox or a disk quota. Use a
trusted test command that obeys the supplied paths. Each medium test has the
repository's 15-second deadline. Teardown sends TERM to the owned process group,
waits up to one second, then sends KILL and waits up to one more second. It also
stops descendants and removes the owned directories.

The `socket_contract` marker selects the portable wire assertions and the
golden scenarios. Tests that inspect Python objects or inject Python failures
keep their `python_daemon` fixture or construct their own Python daemon. They
are outside this marker. Run `uv run pytest tests/test_socket_daemon.py` for the
process fixture's own admission and cleanup checks.

## Transcript contract

Each JSON file records all requests, replies, and consumed subscription events
in one fixed scenario. List and history wait for the required lifecycle event
before reading a queue. They do not discard polling replies or depend on a
sleep. Pause, resume, and skip cover idle transport replies; existing wire tests
cover additional transport and lifecycle behavior. The submit transcript also
pins synthesis-only admission while playback is held.

Comparison retains every object key, array position, and nonvolatile value.
Canonical JSON comparison distinguishes `true` from `1`. The mask has these
explicit rules:

- `id`, `current`, and `ids` values matching `utt_` plus 32 lowercase hex digits
  become numbered tokens. Repeated references keep the same token; different
  identifiers keep different tokens.
- Nonnegative numeric `enqueued_at`, `finished_at`, `submitted_at`,
  `state_changed_at`, and `at` values become `<time>`. Booleans are not times.
- A positive integer `pid` becomes `<pid>`.
- An `audio_path` inside the supplied home replaces that exact home prefix
  with `<home>`. Identifier path components, including WAV stems, use the same
  numbered tokens. External paths stay unchanged.

The mask preserves malformed identifiers and types, nulls, durations, versions,
text, state, playback flags, and unknown fields. It does not normalize expected
files during a test. The checked-in files are change-detection oracles from the
Python 0.2.0 reference, not proof that another implementation is correct. Review
each transcript diff against the protocol when behavior changes; do not update
all goldens to make a failing run pass. Delete a scenario only when its wire
operation is retired. Remove the process fixture when this repository no longer
tests external daemon implementations.
