# AI-TTS store crate

`aitts-store` opens the AI-TTS state database. It uses the same SQLite file and
schema as the Python `aitts.store.Store`, so the Rust daemon and the Python
daemon can open one database during the side-by-side run. It does not change
the schema and it does not write `PRAGMA user_version`.

## Interfaces

`Store::open(path, clock)` creates missing tables, adds the same missing columns
as Python (`generation_artifact_id`, `engine`, `playback`), and fills generation
identity from audio file names. Four small interfaces then read and write it:

| Interface | Operations |
|---|---|
| `Store::queue()` | `submit`, `get`, `segments`, `input`, `playback`, `transition`, `transition_segment`, `recover` |
| `Store::history()` | `list` (newest first, paged by an utterance id), `remove`, `clear` |
| `Store::settings()` | `get` with a default, `has`, `all`, `set` |
| `Store::voices()` | `get`, `list`, `claimed`, `claim` (never replaces a pin), `pin`, `release` |

The caller supplies the clock and mints each `utt_…` identifier. Lifecycle
legality comes from `aitts_domain::utterance::State`. Each write is one
transaction. `recover` is also one transaction: a crash during recovery leaves
the state from before recovery, and the next run repairs it. Python commits
recovery in steps; both converge on the same queue.

## Compatibility evidence

`tests/fixtures/*.db` are databases that the Python daemon wrote, and each
`*.json` is what the Python store read back from it, after `recover()` for the
recovery fixtures. Regenerate them with:

```console
uv run python scripts/generate_store_fixtures.py
cargo run -p aitts-store --example write_golden
```

The second command writes `rust-written.db` with the same operations as
`golden.db`. `tests/test_store_rust_interop.py` checks that Python reads both
files identically.

## Limits

The crate does not yet port synthesis claims, streaming-job creation, playback
suspension, reordering, or audio retention queries from the Python store. It
does not search history (issue #5). It restricts the database file and its
sidecars to mode 0600 on Unix, but it does not create the private parent
directory that the Python adapter creates.
