# AI-TTS artifacts crate

`aitts-artifacts` owns the files that the daemon generates. It uses the same
directory layout and file modes as the Python daemon, so the Rust daemon and
the Python daemon can share one data directory.

This first part has two modules:

| Module | Python source | What it does |
|---|---|---|
| `private_fs` | `aitts.adapters.private_files` | Creates owner-only directories (0700) and files (0600). Opens each path with `O_NOFOLLOW` and sets the mode through the open descriptor. Refuses a symbolic link, and refuses a FIFO without blocking. |
| `audio` | `aitts.adapters.audio_artifacts` | Writes each WAV to `<root>/<id>/.<id>.wav.part`, then renames it onto `<root>/<id>/<id>.wav`. `prepare` deletes candidates that a crash left. |

Not yet in the crate (issue #136 continues): the audio spool
(`aitts.streaming`), the clip evidence and its ZIP export
(`aitts.adapters.clip_evidence`), and the cache inventory.
Retention rules are in `aitts-domain`.

## Checks

```sh
cargo test -p aitts-artifacts --locked
```

Evidence: `docs/testing-evidence/2026-11-16-rust-artifacts-files.md`.
