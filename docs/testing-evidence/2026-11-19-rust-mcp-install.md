# Rust MCP server, part 3 (installation): verification record

Change kind: deliberate behavior change. `make install` now installs the Rust
binary as `ai-tts-mcp` as well as `ai-tts`
([issue #139](https://github.com/flyingrobots/AI-TTS/issues/139)). Parts 1,
2a and 2b are in `2026-11-18-rust-mcp-protocol.md`,
`2026-11-18-rust-mcp-tool-calls.md` and
`2026-11-19-rust-mcp-argument-tools.md`. This record is agent-written and has
not received human editorial review.

## Contract

- After `make install`, `ai-tts-mcp` in uv's tool directory is the Rust
  binary; it serves MCP when started under that name (part 1 tests it through
  a link with that name).
- A host registration made before the change, which stores
  `<tool bin>/ai-tts-mcp`, still names that path, and the path is now the Rust
  binary.
- `make install AITTS_MCP=python` leaves uv's Python `ai-tts-mcp` and keeps
  the Rust `ai-tts`. `AITTS_MCP` follows `AITTS_CLI` unless set, so
  `AITTS_CLI=python` rolls back both and builds no Rust.
- `AITTS_CLI=python AITTS_MCP=rust` builds Rust and installs only
  `ai-tts-mcp` from it.
- A failed Rust build, or an unknown `AITTS_MCP`, replaces nothing.

## Tests and oracles

`tests/test_make_installation.py`, medium: the real `make install` with owned
`uv`, `cargo`, `claude`, `launchctl`, `ps`, `kill` and `uname` in a temporary
root. Assertions read the tool-bin entries, the parsed plist, the recorded
`cargo` arguments and the arguments the owned `claude` received from
`scripts/install-integration.sh mcp --claude`. No real launchd, uv tool
directory, `~/.claude`, `~/.codex` or MCP registration was touched.

New: `test_aitts_mcp_python_rolls_back_only_the_mcp_server`,
`test_the_rust_mcp_server_installs_beside_the_python_cli`,
`test_an_existing_mcp_registration_reaches_the_rust_server` (the upgrade
from the current layout: a Python `ai-tts-mcp` registered with `claude`), and
the `unknown-mcp` case of the replaces-nothing test. The installed-entry-point
contract gained `ai-tts-mcp`, so the default-install, upgrade and CLI-rollback
tests now also state it.

## Observed RED

The tests were committed first; 5 failed on the unchanged installer. During
GREEN the registration test's Python `ai-tts-mcp` stand-in was made
executable, as uv installs it: `install-integration.sh` registers only an
executable, so a plain file let it fall back to another `ai-tts-mcp`.

## Planted faults

| Fault | Failing tests |
|---|---|
| `ai-tts-mcp` not published | default install, upgrade, Python CLI with Rust MCP, registration |
| `AITTS_MCP` not following `AITTS_CLI` | CLI rollback |
| `--mcp` ignored | CLI rollback, MCP rollback |
| Rust built only for `AITTS_CLI=rust` | Python CLI with Rust MCP |
| Any `--mcp` value accepted | unknown-mcp |

`test_aitts_mcp_python_rolls_back_only_the_mcp_server` passed from the start,
because the old installer never replaced `ai-tts-mcp`; the `--mcp` fault
shows it can fail.

## Repetition

The installer test file passed 10 times in a row under pytest-randomly.

## Not verified

- A real install, rollback or host session on a machine: by instruction, the
  installer, `launchctl`, agent configuration and the user's installed
  `ai-tts-mcp` were not run or touched.
