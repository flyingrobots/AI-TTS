# Explicit cached-audio purge evidence — 2026-09-05

Change kind: feature

Oracle: the design's local-confidentiality and cache-ownership rules require a
user-requested purge to remove reusable audio without deleting history text or
interrupting speech that is still owed to the listener

## Boundary and semantics

`CacheController.purge()` is the application policy boundary. It inventories
the cache once, asks the metadata port which paths are still owned by a
nonterminal parent, and classifies each observed WAV as removed, protected, or
failed. Successful removal clears terminal parent/child audio references while
retaining their text rows. Protected artifacts are never passed to the delete
port.

The operation is point-in-time and one-shot. It does not alter the configured
LRU size cap. Audio that is current, queued, synthesizing, ready, or otherwise
owned by nonterminal work remains available so playback cannot be interrupted;
a later purge can remove it after that work becomes terminal. The same typed
receipt crosses the daemon socket, Python application port, CLI, MCP, and
native Swift port. MCP labels the operation destructive and idempotent.

## Feature falsification before implementation

The new boundary tests were added before the feature. The observed failures
were:

- two pure-policy tests failed because `CacheController` had no `purge` method;
- the real daemon contract returned `bad_request: unknown op 'purge_cache'`;
- `ai-tts purge-cache` exited through argparse because the command did not
  exist;
- Unix-socket and MCP test collection failed because
  `PurgeCachedAudioReceipt` did not exist; and
- the focused Swift build failed because `CachePurgeReceipt`, the typed native
  adapter call, and the menu-state action did not exist.

This establishes that the final green results require the new capability
rather than passing through a pre-existing path.

## Probe-driven test correction

The first real-daemon green attempt expected a newly Ready fixture to remain
Ready, but the production playback controller correctly advanced it to
Playing. The test now engages the durable global hold before arranging the
fixture. That controls the state transition without weakening the oracle: the
artifact remains nonterminal and protected, and the assertion can prove that
purge leaves both its bytes and Ready state unchanged.

Review also examined the apparent gap between a worker's final WAV rename and
its SQLite ownership update. Both calls are synchronous and adjacent in one
daemon event-loop turn; purge dispatch is synchronous on the same loop. The
existing gated synthesis schedule was strengthened to invoke purge while the
engine thread holds a partially written `.part` candidate. Purge observes no
cache entry and removes nothing, the candidate remains intact, and after the
gate opens the final WAV and Ready metadata appear together. This preserves
the no-gap invariant without adding a second lock or a timing heuristic.

## Assertion calibration

Five temporary control mutants were run independently and restored:

1. Replacing the metadata-provided protection set with an empty set made both
   the pure policy and real-daemon tests fail. The receipt changed from two
   removed files / 13 bytes plus one protected file / 6 bytes to three removed
   files / 19 bytes plus no protection.
2. Omitting terminal-reference cleanup made the pure test report no forgotten
   paths and left the real terminal utterance's `audio_path` populated after
   its file was gone. Both tests failed.
3. Registering the MCP tool with the ordinary write annotation made tool
   discovery report `destructive_hint: false`; the exact annotation assertion
   failed.
4. Renaming `cache_changed` to `cache_stale` made the subscriber-event
   assertion fail while the request receipt still passed.
5. Removing Swift's nonnegative-value guard made a daemon receipt with
   `removed_files: -1` decode successfully; the fail-closed adapter test failed
   because no `invalidResponse` was thrown.

## Final verification

The restored exact tree passed:

- 25 focused Python cache/artifact/IPC/CLI/Unix-adapter/MCP tests;
- 3 focused Swift cache-purge tests;
- all 236 Python tests in 5.19 seconds;
- all 74 Swift tests under the repository's 60-second deadline;
- Ruff lint and format checks, strict mypy, `uv lock --check`, and
  `git diff --check`;
- `actionlint` and `zizmor 1.28.0` offline with no findings; and
- an offline wheel and source distribution accepted by
  `check-wheel-contents` and `twine check`.

A production Swift app bundle was also built from the exact tree, ad-hoc
signed, and accepted by `codesign --verify --deep --strict` and `plutil -lint`.
Its arm64 executable SHA-256 was
`da9ec10f29a9fb7224a6d5280b8b708386e7009a86909a390e15a327c2a56040`.

## Remaining installed acceptance boundary

This slice verifies policy, every programmatic client boundary, menu-state
feedback, SwiftUI compilation, and a production bundle. It did not replace or
relaunch the user's installed menu-bar app, open Settings, or perform a visual
click-through. Those external-state changes require a separately coordinated
installed UI acceptance; no visual acceptance is claimed here. The artifact
also remains thin arm64 and ad-hoc signed, so this does not close the broader
Developer ID, notarization, or architecture-policy release gates.
