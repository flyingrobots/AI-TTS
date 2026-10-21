# Agent speech returns at queue admission

Change-kind: behavior change.

The default speak skill no longer requests `say --wait`. The daemon and MCP
submission already acknowledge admission with a stable utterance ID. The CLI
now exposes the existing socket `get` operation for a separate immediate lookup.
Explicit `say --wait` and `wait` retain their playback-completion behavior.

The installed-skill test reads the rendered default command. Restoring the
parent skill makes its no-wait assertion fail (one failed test); restoring the
candidate passes. The owned real-daemon CLI journey holds playback, submits,
looks up the same ID/text in a pending state, cancels, then observes Cancelled.
An absent-ID case requires exit 1 and not_found. Redirecting get to status makes
both lookup tests fail; restoring the candidate passes. Bytecode was cleared
and disabled during calibration. These medium tests own their socket, store,
engine, sink and installer destinations. No real audio or global settings are
used by automated tests. Retire with removal of these public contracts or a
stronger calibrated replacement.

Validation: 80 focused CLI, installer, MCP and client tests pass; changed-file
Ruff and CLI mypy pass. A pre-existing newline-path test selected the second
Markdown code block by position; adding the get example exposed that assumption.
It now selects the status command by arguments and retains exact pathname
preservation. The first pytest invocation imported another worktree through the
existing editable environment; that result was discarded. All accepted runs
explicitly use PYTHONPATH=src.

The updated skill was installed for Claude, Codex and Gemini under the shared
host/agent-settings/ lock. New sessions load it. The installed package and live
daemon were not replaced: the new get CLI command requires a package upgrade.
The installed skill documents list/history lookup for older CLIs. The project
announcement used the live admission-only say path and returned accepted with
an ID; this receipt establishes admission, not acoustic playback.

The complete Python/Swift suites and physical listening were not run for this
scoped change. The daemon lifecycle/storage/state machine is unchanged.

## PR preparation against current main

The change was isolated from the original branch's unrelated queue-cue commit
and applied to main 3345ad6. Conflicts retained main's corrected TUI installation
hint assertion and full compliance ledger, then appended only the new lookup
tests and admission entry. Validation on this isolated candidate: 81 focused
CLI, installer, MCP and client tests pass; changed-file Ruff, CLI mypy and diff
whitespace checks pass. Imports explicitly use this worktree's src directory.
