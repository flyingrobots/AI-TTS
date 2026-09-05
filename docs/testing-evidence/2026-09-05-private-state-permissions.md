# Owner-only private-state evidence — 2026-09-05

Change kind: bug fix

Oracle: `SECURITY.md` and architecture section 9 require persisted speech and
audio to be readable only by the owning user

## Red on the unfixed code

The regression module was run against commit `3a74c16` before the production
implementation changed:

```text
uv run --frozen pytest tests/test_private_state_permissions.py -q
FFFF                                                                     [100%]
4 failed
```

All four behavior checks failed for the intended reason:

1. Under an explicit process umask of `0000`, a new state directory was `0777`
   and `state.db`, `state.db-wal`, and `state.db-shm` were `0644`, rather than
   the owner-only `0700` / `0600` contract.
2. Starting a daemon over a seeded legacy layout retained `0750` directories,
   a `0640` database and sidecars, and a `0644` cached WAV. Only the socket was
   already `0600`.
3. Under the same permissive umask, the synthesis cache directory remained
   `0777` and both the in-flight candidate and published WAV were `0666`.
4. A symlink used as the daemon home was followed, creating `state.db` in its
   target instead of refusing the ambiguous ownership boundary.

These observations reproduce the audit finding and calibrate every new
load-bearing assertion against the unfixed behavior.

## Fix and green verification

The filesystem adapter now creates or opens private paths through no-follow
file descriptors and applies modes with `fchmod`: `0700` for owned directories
and `0600` for regular files. Daemon assembly normalizes existing state before
opening SQLite. The SQLite adapter pre-creates its database privately and
normalizes existing and live WAL, SHM, and journal sidecars. The audio adapter
pre-creates a private candidate before synthesis, preserves that mode through
atomic publication, and normalizes existing cache members during startup and
inventory.

The focused regression completed with `4 passed`. The adjacent store, IPC,
cache, synthesis, and artifact contract run completed with `90 passed`.

The complete Python suite completed with `218 passed`, and the unchanged Swift
suite completed with `66 passed`. Ruff lint/format and strict mypy also passed.
An isolated Python 3.12 environment installed the newly built wheel, then ran a
fake-engine daemon under umask `0000`; its live state directory, cache
directory, database, WAL, SHM, socket, and synthesized WAV all reported the
contracted `0700` / `0600` modes. The source distribution, wheel, and native
app bundle were all rebuilt successfully outside the worktree.

## Remaining boundary

This evidence covers creation under a deliberately permissive umask, migration
of modes owned by the current user, no-follow handling of the final state-root
component, SQLite sidecars while the store is live, and both candidate and
published audio. It does not claim encryption at rest, protection from a
process already running as the owning user, repair of paths owned by another
account, or exhaustive defense against replacement of ancestor directories by
an attacker who already controls the user's account. Those cases remain
outside the stated local-single-user threat model.
