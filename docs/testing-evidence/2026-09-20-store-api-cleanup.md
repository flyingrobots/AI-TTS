# Store API cleanup publication

Change-kind: behavior change

This publishes the existing local commit `e61e6d8`, originally written for
issue #11, as isolated commit `ff99614` on `origin/main` at `7e78913`.
The internal Store API loses an unused method and marks an internal helper
private. No user-facing playback behavior is intended to change. The change
kind describes the narrowed internal interface and changed assertions rather
than claiming an assertion-preserving refactor.

## Scope and oracle

Issue #11 asks to remove `head_of_plan` if unused and rename `pending_queue`
when only the store calls it. Source inspection confirms `rewind --to` uses
`move_to_head`, not the removed method. The updated queue-order assertion
continues to exercise `move_to_head` through `input_queue`.

The two existing tests in `test_store_surface.py` are explicitly small and
name the source-consumer contract as their oracle. They inspect production
call sites by method name. This is a heuristic, not a semantic call graph:
name collisions can hide an unused Store method. These checks do not prove
behavioral equivalence. Retire them if Store gains an external API or a
stronger semantic analysis replaces this internal-only convention.

## Falsification

In the isolated worktree, temporarily replaced only `src/aitts/store.py`
with its `origin/main` version and ran:

```sh
.venv/bin/pytest tests/test_store_surface.py
```

Both tests failed for their named reasons:

- Public methods without an external source caller: `head_of_plan` and
  `pending_queue`.
- Public method used only inside Store: `pending_queue`.

Restored the committed cleanup immediately afterward. No mutation touched
the original checkout or running daemon. The original commit's message also
records its earlier red-first observations and why the deleted lookup test
was retired; this publication independently reproduced those failures.

## Validation environment

Checkout: `/Users/james/git/ai-tts-store-cleanup`, branch
`refactor/store-api-cleanup`, its own `.venv`, CPython 3.13.11, dependencies
installed with `uv sync --frozen --dev`. Ruff lint and format checks and mypy
passed. The mandatory pre-push hook passed all 557 Python tests in
13.21 seconds and the Swift build. No Swift source changed. This branch excludes the separate
microphone-resume fix in PR #23.
