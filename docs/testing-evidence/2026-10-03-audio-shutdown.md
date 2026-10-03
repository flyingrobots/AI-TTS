# Prepared audio shutdown and daemon liveness

Change-kind: bug fix. [Issue #94](https://github.com/flyingrobots/AI-TTS/issues/94). Unfixed parent: `a9b9f23`.

## Failure and change

Switching from Kokoro-MLX's persistent callback output to Chatterbox's mono 24 kHz FLOAT WAV selected the general file-output path. Closing the prepared output set both its stop request and its native-completion event. Its owner therefore entered `Pa_StopStream` before the native finished callback, concurrently with callback-driven shutdown. Incident stacks showed both stop paths blocked in CoreAudio and the event loop blocked in a synchronous microphone-property query. The exact native mutex ownership was not captured; this is a strongly supported causal diagnosis, not a deterministic reproduction of the operating-system deadlock.

Only native completion now releases the prepared context. Renderer errors also wait for native completion. A close timeout retains the owner; preparation refuses to reuse an output whose stop was requested. The original five-second production close deadline is unchanged. No device reinitialization or replacement is allowed through this object until its worker finishes. There is no claim that Python can interrupt a stuck driver.

Microphone reads use one dedicated daemon thread per watcher run and one outstanding request. Transport/state actions remain on the event loop. The watcher marks an outstanding reading unavailable, preserves edge-detector history, and discards results after cancellation. It does not use the default executor, whose interpreter-shutdown join would otherwise preserve the hang. One blocked native worker may remain until process exit; it cannot access the store or controller, enqueue further probes, or prevent interpreter exit.

## Owned experiments

All new cases are medium with explicit oracles. They use owned files, threads, socket paths and subprocesses; no hardware or installed service participates in CI.

| Experiment | Boundary and oracle | Observed failure / calibration |
| --- | --- | --- |
| Explicit stop with native completion withheld | Prepared output must refuse cleanup and reuse until native completion; native context records completion ordering | On parent, close returned instead of raising; removing the stopping-output guard separately makes preparation wrongly succeed |
| Renderer exception with native completion withheld | Logical failure may release its renderer, but only native completion releases the hardware | On parent, close returned early; restoring premature completion in the exception path independently fails the refusal assertion |
| Prepared PCM to FLOAT WAV | Sink cannot open/write general output while callback ownership remains; retry plays after completion | Parent attempted general output with context exit recorded before native completion, yielding the wrong error; fixed code refuses the first attempt and plays the retry |
| Native open failure then retry | Preparation surfaces the native error and subsequently admits exactly one successful owner | Omitting the preparation error check produces a missing-exception failure |
| Blocked input read | Real daemon status and shutdown complete while the owned read remains held; only one read is outstanding | Parent freezes status until the owned watchdog releases the native read; exact assertion: `status waited for the blocked native input read` |
| Process exit with blocked read | A fresh interpreter runs/cancels the watcher and exits while its native read remains blocked | Changing the probe to a non-daemon thread makes the child exceed its three-second deadline |

The held-device tests shorten the close deadline to 50 ms; they assert refusal/ordering, not measured speed. The input watchdog exists because an asyncio timeout cannot rescue an event loop blocked by the unfixed code. A first draft of that test failed during fixture construction due to a missing fake-engine voice argument; that run is not counted as red evidence. After correcting the fixture, the unfixed source failed at the status-liveness assertion and the fixed source passed.

Existing manual callback doubles now supply callbacks during blocking close/reprepare and daemon teardown, matching the native completion contract rather than silently relying on premature context exit. Their playback/transport oracles are unchanged. Retire these regressions only if the relevant lifecycle is removed or replaced by an equivalently calibrated native ownership and daemon-liveness contract.

## Validation

- Four new regression cases were observed red on unfixed source; six final cases pass, including preparation recovery and interpreter shutdown.
- Four seeded faults above were observed red and restored before verification. Python bytecode was invalidated between mutation and restoration.
- Full Python suite: 1,038 passed; 341 small tests charged 0.80 seconds and 697 medium tests charged 38.32 seconds; total wall clock 41.41 seconds. No skipped/retried failures were accepted.
- Focused existing playback/input suite plus the initial regressions: 79 passed in 1.68 seconds.
- Native manual experiment: ten successive silent prepared-PCM → FLOAT-WAV → close cycles passed on macOS 27.0.1 / arm64 using the installed Python 3.12 runtime with candidate source. Each sink reported natural completion without error before closing. The WAVs were generated zeros; this verifies lifecycle completion, not acoustic quality or model inference.
- The pre-fix diagnosis completed ten native close cycles and another 96 within a bounded longer run without reproducing the native deadlock. Therefore successful post-fix cycles are supporting integration evidence, not a statistical reliability claim or a native red-to-green reproduction.

Ruff, formatting, mypy, frozen lock verification and hosted CI are recorded in the linked PR. Hardware/driver changes, a permanently stuck output thread, long-lived sessions and acoustic listening remain outside the hermetic proof. Connection-state UI wording is unchanged.
