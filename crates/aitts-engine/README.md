# aitts-engine

The Rust daemon's speech engines. The Python daemon is unchanged.

| Module | Owns |
|---|---|
| `engine` | The `Engine` interface (`stream` gives audio blocks to a sink) and typed, content-free errors. |
| `registry` | Named engines; a name is registered once. |
| `worker` | `WorkerSupervisor`: one Python model worker over protocol version 2. |
| `loopback_http` | Speech through a separately managed OpenAI-compatible server on loopback. |
| `catalog` | The three worker models and their pinned digests, read from `src/aitts/model_digests.json`. |
| `setup` | The setup check that every installed model file has its pinned SHA-256. |

## Worker supervisor

The supervisor starts `ROOT/venv/bin/python -m aitts.model_worker serve MODEL ROOT 3`
with the offline environment of `src/aitts/engines/managed.py`. Descriptor 3 is
the audio pipe; only the worker holds its write end. The first control line must
be `{"protocol": 2}`.

- The worker leads its own process group. A stop sends `SIGKILL` to the group
  while the leader is still unreaped, then reaps it, so the group identifier
  cannot be reused first (issue #105). `ESRCH` and Darwin's `EPERM` for a group
  of zombies are benign.
- A worker that is silent for longer than the response time limit is stopped
  with its children and the request fails with `Timeout`.
- Any failure (exit, timeout, invalid frame, wrong pipe, model failure) stops the
  worker and sets the state to `Failed`. A failed worker is not started again by
  a request; `restart()` starts it and sends `warmup`.
- A stream that fails returns `Err`. Audio already given to the sink is then a
  partial clip, and the caller must discard it.

## Limits

- `loopback_http` supports plain HTTP only. It refuses HTTPS, remote hosts,
  credentials, queries and fragments, follows no redirects, and gives the whole
  WAV body to the sink once. It does not decode or validate the WAV.
- `setup` verifies files. Download, the private runtime and publication remain
  in the Python `ai-tts model-setup`.
- There is no native Rust model engine.

## Tests

`cargo test -p aitts-engine`. The supervisor tests run
`tests/fixtures/fake_worker.py` through `python3`. Evidence:
[`docs/testing-evidence/2026-11-16-rust-engine.md`](../../docs/testing-evidence/2026-11-16-rust-engine.md).
