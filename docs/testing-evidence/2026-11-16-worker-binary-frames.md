# Worker audio as binary frames

Change-kind: feature with a deliberate protocol change, issue [#126](https://github.com/flyingrobots/AI-TTS/issues/126).

## Protocol version 2

- The daemon opens a second pipe for each worker and passes its write end as a fourth `serve` argument (`pass_fds`). The daemon closes its own copy, so worker exit is an end of file on the audio pipe.
- The worker's first control line is `{"protocol": 2}`, written before the model loads. The daemon reads it when it starts the worker. A different value, a non-integer value, another first message, or an exit before any message raises `WorkerProtocolError` (a `SynthesisError`), and the daemon stops that worker. A worker copied by an older AI-TTS exits on the extra argument, so it gets this typed refusal. Refresh the worker in model setup to fix it.
- Control requests and replies stay JSON lines on stdin and the private stdout duplicate.
- During `stream`, each audio block goes to the audio pipe as a 4-byte big-endian length and then the bytes. One frame holds at most 512 KiB; the worker splits a larger block into several frames. Empty blocks are not sent. The empty frame ends every stream, also when the model fails, and then the control reply (`{"ok": true}` or `{"ok": false}`) follows.
- The daemon reads a frame header and body exactly. End of file inside a frame, or a length above 512 KiB, is `model worker returned an invalid response`. It never yields a partial frame.
- The runtime manifest field `worker_protocol` (`model_catalog.WORKER_PROTOCOL_VERSION`) is not changed. It describes the installed layout, not the wire protocol, so existing installations stay installed and need only a worker refresh.

## Observed red (parent 4b1c6ca)

All new tests in `tests/test_managed_engine.py` failed on the parent: the codec and handshake tests with `AttributeError` (no `encode_frame`, `FRAME_LIMIT`, `read_frame`, `WorkerProtocolError`, `protocol_version`). For a semantic red, the golden test was run on the parent with the limit written as the literal 524288: the 1.5 MiB block failed with `SynthesisError: model worker returned an invalid response`, because its base64 JSON line was longer than the 512 KiB line limit.

## Falsification

Each fault was applied alone, the named tests were run, and the fault was reverted.

| Fault | Witness | Result |
|---|---|---|
| Short read returns the partial bytes as a full frame | partial-frame tests, fuzz, golden | 16 failures |
| Frame length limit not checked | frame above the limit | `DID NOT RAISE` |
| Version value not compared (type only) | another protocol version `{"protocol": 1}` | failed |
| Worker does not split blocks above the limit | golden byte-for-byte | `SynthesisError` |
| End frame written only on success | model failure inside a stream | pytest timeout |

The first version of the limit test sent only a header. It survived the limit fault, because end of file also refused it. It now sends the full oversized body.

## Review fixes (CodeRabbit on PR #183)

| Finding | Red on 701298e | Fix |
|---|---|---|
| A spawn failure left the audio read descriptor open | `test_failed_worker_starts_leak_no_audio_descriptor`: five failed starts, `assert 17 == 12` open descriptors | `_start` closes and clears the read end when the spawn raises |
| `close()` racing a stream's cleanup closed the audio descriptor twice | `test_close_during_stream_exit_detaches_the_worker_exactly_once`: the whole `close()` runs inside the stream's `os.close` (injected, no sleeps); `OSError: [Errno 9] Bad file descriptor` | `_stop_worker` detaches the process and descriptor once under a separate lifecycle lock and closes them through locals; `close()` never takes the synthesis lock |

Both tests pass after the fix; the full suite gives 1313 passed, 2 skipped.

## Time to first audio

Acceptance: not more than before. Measured with `ManagedStreamingEngine` against a fake worker that yields one block of silence at once, so the figure is only the transfer cost on the path to first audio (spawn and model time are the same in both). 200 warm requests each. Apple M5 Pro, macOS, Python 3.14, load average about 9, 2026-11-16.

| First block | Before (base64 JSON line), median / p90 | After (binary frame), median / p90 |
|---|---|---|
| 48,000 B (1 s of 24 kHz PCM) | 0.200 / 0.214 ms | 0.026 / 0.030 ms |
| 240,000 B (5 s) | 0.938 / 1.329 ms | 0.070 / 0.079 ms |

## Commands

```sh
uv run pytest tests/test_managed_engine.py
uv run pytest tests/          # 1311 passed, 2 skipped
uv run ruff check && uv run ruff format --check && uv run mypy
```

## Not verified

- No run with the real Kokoro, Kokoro MLX or Chatterbox runtimes; the fake worker uses the real worker and daemon code with a fake model.
- The time to first audio figures cover only the transfer, not a real model.
