# AI-TTS artifacts crate

`aitts-artifacts` owns the files that the daemon generates. It uses the same
directory layout and file modes as the Python daemon, so the Rust daemon and
the Python daemon can share one data directory.

It has six modules:

| Module | Python source | What it does |
|---|---|---|
| `private_fs` | `aitts.adapters.private_files` | Creates owner-only directories (0700) and files (0600). Opens each path with `O_NOFOLLOW` and sets the mode through the open descriptor. Refuses a symbolic link, and refuses a FIFO without blocking. |
| `audio` | `aitts.adapters.audio_artifacts` | Writes each WAV to `<root>/<id>/.<id>.wav.part`, then renames it onto `<root>/<id>/<id>.wav`. `prepare` deletes candidates that a crash left. |
| `spool` | `aitts.streaming.SpoolingPCMStream` | Writes 16-bit mono 24 kHz PCM to an owner-only WAV and feeds a bounded in-memory ring. `read` reads only the ring; `fill` moves overflow or seeked audio from the file. `seal` writes the same header bytes as Python's `wave` module. `open_cached` streams a finished WAV without changing it. The owner does the locking and runs `fill` on its feeder thread. |
| `evidence` | `aitts.adapters.clip_evidence.ClipEvidence.export` | Writes a new owner-only evidence ZIP with the Python entries, order and manifest. The caller passes the export time and runtime description. Symbolic links are never exported; audio outside the cache root is refused and the partial archive deleted. |
| `records` | `ClipEvidence.submitted`, `prepare`, `record`, `generated`, `audio_generated` | Writes `source.txt`, `request.json`, `audio.json` (hashes, format and peak, clipped and non-finite sample counts of a 16/24-bit PCM or 32-bit float WAV), `generation.json`, `model.json` and the `synthesis`/`playback` JSONL logs in owner-only clip directories. Lines use Python's `json.dumps` separators, so a log rotates to `<phase>.previous.jsonl` at the same event (1 MiB limit). The caller supplies the clock, session and runtime; write errors are returned. |
| `cache` | `aitts.adapters.generated_storage.GeneratedStorage` (`inventory`, `remove`) | Lists each clip directory and legacy `<id>.wav` as one row (bytes, newest time, protection, 160-character preview), newest first, and deletes the named unprotected clips. Symbolic links are skipped. Expiry is a retention rule in `aitts-domain`. |

The spool writes through `SpoolStorage`; a file implements it, and tests use a
double that reports a full disk.
Retention rules are in `aitts-domain`.

## Checks

```sh
cargo test -p aitts-artifacts --locked
```

Evidence: `docs/testing-evidence/2026-11-16-rust-artifacts-files.md` and
`docs/testing-evidence/2026-11-17-rust-audio-spool.md`, and
`docs/testing-evidence/2026-11-17-rust-evidence-export.md`, and
`docs/testing-evidence/2026-11-17-rust-evidence-records.md`, and
`docs/testing-evidence/2026-11-17-rust-evidence-writers.md`, and
`docs/testing-evidence/2026-11-17-rust-cache.md`.
