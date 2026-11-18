# Rust command-line client, part 3 (installation): verification record

Change kind: deliberate behavior change. `make install` now installs the Rust
`ai-tts`, the Python CLI as `ai-tts-py`, and a launch agent that runs
`ai-tts-py daemon` (issue #138). Parts 1 and 2 are in
`2026-11-16-rust-cli.md` and `2026-11-18-rust-cli-wait.md`. This record is
agent-written and has not received human editorial review.

## Contract

- After `make install`, `ai-tts` in uv's tool directory is the Rust binary,
  `ai-tts-py` is the Python CLI, and the launch agent's `ProgramArguments`
  start with `<tool bin>/ai-tts-py daemon`.
- An installation from the earlier layout (launchd running the Python
  `ai-tts`) ends in that layout, with the service loaded.
- `make install AITTS_CLI=python` (rollback) leaves the Python `ai-tts`, runs
  no Rust build, and keeps the launch agent on `ai-tts-py`.
- A failed Rust build, or an unknown `AITTS_CLI`, replaces nothing.
- The Rust `ai-tts` hands `daemon` and `tui`, after an optional `--socket`,
  to `ai-tts-py` with the same arguments and returns its exit status; all
  other commands stay in the Rust binary; without `ai-tts-py` it exits 1.

## Tests and oracles

| Test | Size | Oracle |
|---|---|---|
| `tests/test_make_installation.py`, 5 new tests and 2 changed | medium | The real `make install` with owned `uv`, `cargo`, `launchctl`, `ps`, `kill` and `uname` in a temporary root. Assertions read the parsed plist `ProgramArguments`, the content of each tool-bin entry, and the recorded `cargo` arguments. No real launchd, uv tool directory or `~/Library` is touched. |
| `test_the_python_package_installs_its_cli_as_ai_tts_py` | medium (file) | `pyproject.toml` console scripts: `ai-tts-py` and `ai-tts` are both `aitts.cli:main`. |
| `crates/aitts-cli/tests/delegate.rs`, 3 tests | medium | A copy of the built binary beside a stand-in `ai-tts-py` that records its arguments and exits 7. |

The two changed installer tests expected the launch agent to run
`<tool bin>/ai-tts`; they now expect `ai-tts-py`. That is the intended
behavior change.

## Observed RED

The tests were committed first. On the unchanged installer and binary, 8
installer tests and 2 of the 3 delegation tests failed.
`client_commands_stay_in_the_rust_binary` passed from the start, because the
old binary delegated nothing; the planted fault below shows it can fail.

## Planted faults

| Fault | Failing tests |
|---|---|
| Launch agent runs `ai-tts` | 5 installer tests |
| Rust binary not published | the default-install and upgrade tests |
| `AITTS_CLI=python` still builds and publishes Rust | the rollback test |
| Rust built after `uv tool install` | `test_a_failed_rust_build_..._replaces_nothing[cargo]` |
| No hand-off | 2 delegation tests |
| Hand-off when `daemon` is any argument (`say daemon`) | `client_commands_stay_in_the_rust_binary` |
| `--socket` value not skipped | `daemon_and_tui_reach_ai_tts_py_...` |

## Repetition

The installer test file passed 10 times under pytest-randomly; the
`aitts-cli` tests passed 10 times in a row (stable libtest has no shuffle).

## Not verified

- A real `make install` or rollback on a machine: by instruction, the
  installer, `launchctl` and the user's installed `ai-tts` were not run or
  touched.
- Whether `uv tool uninstall` removes a tool-bin entry that was replaced;
  `make uninstall` removes `ai-tts` itself in case it does not.
