# AI-TTS daemon crate

`aitts-daemon` builds `ai-ttsd`, the Rust daemon. This first version owns the
process lifetime and the socket, and it answers the operations that only read
state. It runs no engine and plays no audio. `make install` does not install it;
the Python daemon is still the daemon that users run.

## Run it

```console
cargo run -p aitts-daemon --bin ai-ttsd
```

It reads `AI_TTS_HOME` (default `~/Library/Application Support/ai-tts`) and
`AI_TTS_SOCKET` (default `<home>/ai-tts.sock`), like the Python daemon. It opens
`<home>/ai-tts.db` and measures `<home>/cache`. SIGTERM, SIGINT, or SIGHUP stops
it within 3 seconds; after that limit it removes the socket and exits anyway.

## Start and stop

1. Take an advisory `flock` on `<socket>.lock`. This is the same lease as the
   Python `ExclusiveFileLease`, so a Rust daemon and a Python daemon exclude
   each other. A second daemon exits with `another daemon is already running`.
2. Open the state database through `aitts-store`.
3. If a socket file is at the path and no process accepts on it, remove it. A
   non-socket entry or a symbolic link is kept, and start fails.
4. Bind the socket and set mode 0600.

Stop closes every connection, closes the store, removes the socket, and
releases the lease.

## Concurrency model

One thread accepts connections. Each connection has its own thread, which reads
lines of at most `aitts_protocol::MAX_REQUEST_BYTES`. One API thread owns the
store and answers requests in arrival order, as the single Python event loop
does. A client that sends half a line blocks only its own thread.

A `subscribe` request gets its acknowledgement, then events. Each subscriber
has a backlog of 256 event lines and its own writer thread. A broadcast never
waits on a socket: when a backlog is full, the daemon closes that connection,
so the client knows it missed events and other subscribers continue.

## Operations

| Operation | Reply |
|---|---|
| `status` | Counts from the store, the persisted playback hold, the configured engine and voice. Nothing is current. |
| `get`, `list`, `history` | The Python projections of stored utterances, including segment readiness and history fields. |
| `voices` | The configured engine catalog. The binary configures `kokoro` with no voices. |
| `settings` without `set` | Every setting as Python `SettingsService.values` reports it. |
| `metrics` | Counts, queue depth, cached WAV bytes, and the cache limit. Timing statistics are null. |
| `snapshot` | All of the above, one engine, and no model setup catalog. |

Every other operation, and `settings` with `set`, gets a `bad_request` reply.
Malformed JSON and requests outside the wire contract also get `bad_request`.

## Limits

- `status` reports `accepting_speech: true`, because the wire contract allows
  only that value, but `submit` is refused.
- `status` reports version `0.1.0`, the crate version.
- The daemon does not run restart recovery, because recovery writes.
- Error messages are not byte-identical to Python messages; error types match.
- There is no connection limit and no daemon log yet.
- As in Python, the socket exists with default permissions between `bind` and
  `chmod`. The binary creates a missing home or socket directory with mode
  0700, which limits who can reach it; it does not change an existing one.

## Evidence

[The verification record](../../docs/testing-evidence/2026-11-16-rust-daemon-skeleton.md)
lists the tests, their oracles, and their failure demonstrations.
