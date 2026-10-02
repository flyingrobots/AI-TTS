# Streaming audio acceptance

Change-kind: feature

The user approved shipping prompt 3 with measured 194–205 ms startup and tracking
the original under-150-ms target separately in
[issue #33](https://github.com/flyingrobots/AI-TTS/issues/33). The agreed benchmark
is an eight-word sentence on this Mac using the fastest supported local backend.
This acceptance does not claim that 150 ms was achieved. The 194–205 ms readings
used a 240-frame callback block. They predate the device-rate host block adopted on
2026-10-01, which raised the stream's reported output latency by about 33 ms, and
they have not been re-measured. The installed application
remains on the earlier committed release; this change has not been installed.

## Contract and validation

The callback consumes only memory. Synthesis spools private PCM to a WAV and
feeds a bounded ring; overflow and backward seeks use a separate file feeder.
Publication and durable metadata release EOF. Pauses do not block generation,
and inserted underrun silence does not advance the source playhead.

The prepared physical output emits silence between logical speech sessions,
including long pauses, and closes on route changes or daemon shutdown. Existing
compatible cached WAVs use the same callback path without rewriting them. The
reference Kokoro and MLX adapters yield bounded 100 ms PCM buffers. MLX uses its
upstream `generate_stream` API under the engine lock: phoneme chunks can become
playable before later chunks finish; individual model chunks still require a
complete forward pass.

Each test count in this receipt is historical. It was taken at a different stack state and belongs to the section that reports it: 638 here, 634 in the leading-zero optimization run, 689 and 793 in the main reconciliation (the integrated stage and the combined stack), and 771 after the streaming review regressions on `954807b`. The 730 in the testing profile's installer section is main's count, not this branch's. The authoritative count for the current head is in the last section, "Merge with main and review round".

Paths under `/tmp/` and `.git/codex-scratch/` are raw logs on the authoring machine. They are not in the repository and cannot be reproduced from it. The text summarizes the red output each one held.

Validation for this section (historical): **638 Python tests passed**, 228 small / 410 medium. Measured class
costs including fixtures: 0.51 s / 7.37 s, within 10 s / 45 s budgets. Full wall
clock 8.32 s. Ruff, format checks, mypy (110 files), and diff checks passed.
The full run is `/tmp/streaming-release-suite.log` (local only).

New boundary coverage includes:

- bounded ring wraparound and sample order; early playback with the final engine
  block behind a controlled gate; complete cached WAV bytes;
- starvation versus EOF, bounded sample-to-sample fade, source-clock preservation,
  resume fade, failure-to-silence, and native pause/resume while the producer
  exceeds ring capacity;
- native callback EOF only after publication; generation, publication and
  durable-metadata failures remove candidates and terminate playback;
- nested preemption and exact saved offsets before files are published; rewind;
  shutdown while native inference remains gated;
- standalone and later-child composite crash recovery, preserving completed
  children and holding playback; repeated recovery and seeded commit failures
  during admission, publication and recovery;
- prepared output reuse, idle silence, route changes, unexpected device closure,
  callback exceptions, and late preparation after shutdown;
- cached-file read-only seeking and invalid-file rejection; bounded/lazy local
  Kokoro and MLX PCM, including exact quantization and offline asset resolution.

These are contractual boundary tests with explicit size/oracle declarations.
Delete or rewrite them when the corresponding behavior changes, not when the
private implementation moves. No automated test uses real speakers or weights.
Historical: when this section was written, the draft changed no Swift, and the latest Swift receipt was 112 tests, in [the XCTest invocation change](2026-09-30-xctest-invocation.md). The streaming feature itself still changes no Swift. Merges from main have since brought in Swift changes, so the current Swift count is in the last section.

## Observed red and assertion calibration

The original daemon test timed out waiting for playback despite witnessing the
first engine yield (`/tmp/streaming-pipeline-red.log`). The same gated scenario
passes with streaming admission. Generation/publication fault tests initially
observed a last sample of 0.25 instead of silence
(`/tmp/streaming-failure-red.log`); the renderer now fades on error. A metadata
publication failure initially left the clip outside Failed and killed worker
progress (`/tmp/streaming-metadata-red.log`); it now discards the unowned WAV,
records failure and terminates the live source. The upstream MLX lazy-chunk test
first failed while the adapter still used whole-result generation
(`/tmp/mlx-lazy-stream-red.log`).

Seeded mutations were applied one at a time and restored in `finally`. The
following faults produced assertion failures, not collection or syntax errors:

| Fault | Contract witness |
|---|---|
| Drop first ring sample | bounded sample order |
| Signal EOF before publication | sealed stream remains unfinished |
| Zero the disk spool | cached WAV exactly matches generated PCM |
| Ignore backward seek | spool resumes at requested samples |
| Remove starvation decay | bounded difference between adjacent output samples |
| Advance clock during inserted silence | source-only playhead |
| Skip persisted streaming recovery | queued, retained standalone source |
| Forget recovery hold | completed child retained, unfinished child held |
| Skip early admission | first-yield witness before playback deadline |
| Route live source as a file | nested unpublished preemption |
| Drop saved live offset | exact nested resumption offsets |
| Remove error fade | final callback ends at zero |
| Open cached WAV for writing | existing bytes preserved and playable |
| Omit idle silence | every idle output sample zero |
| Remove prepared-device reuse | one refresh for successive sessions |
| Hide device closure | active session reports physical failure |
| Permit preparation after shutdown | no device opened after shutdown |
| Emit unbounded/drop MLX chunks | exact chunk lengths and concatenated samples |
| Ignore native pause | held playhead and silent callbacks |
| Propagate callback exception | owned failure, silence, released session |
| Drop source error | publication failure ends logical playback |

One important initial survivor was **removing the starvation fade**: checking
only the first and last samples missed an abrupt drop in the middle of the
block. The assertion was strengthened to bound every adjacent-sample change.
The same mutation then failed with a 0.5 jump against a 0.5/119 bound. This is
recorded explicitly rather than reporting the original calibration as green.

Local raw receipts: `/tmp/streaming-calibration.json`,
`/tmp/streaming-calibration-extra.log`, `/tmp/stream-fade-calibrated-red.log`.
The seeded SQLite fault adapter and rollback mechanism also retain their
existing Store test coverage; new cases exercise streaming-specific writes.

## Controlled hardware experiment

[Raw baseline and current readings, with environment](2026-09-30-streaming-latency.json).
Apple M5 Pro, 64 GiB, macOS 27.0; Python 3.12.14, kokoro-mlx 0.1.2, MLX 0.32.3.
The eight-word workload is “This is a controlled streaming speech latency test.”
Voice bm_daniel, speed 1.0, cached `mlx-community/Kokoro-82M-bf16` weights. The
reference CPU backend was slower: a prior five-run first-PCM median was 404.26 ms.

Model warmup and a priming inference precede timing. Submission traverses an
owned Unix socket and the daemon's actual synthesis/playback paths. The native
PortAudio callback records source progress and nonzero output separately, then
**zeros the hardware output**. Completion uses a state event. No generated speech
was played, no download was allowed, and no automated suite ran concurrently
with the five baseline trials below.

These are the **baseline trials, taken before the leading-zero skip**. The headline 194–205 ms comes from the later run described under "Leading-zero playback optimization". Table trials 1–5 are JSON `baseline_trials` entries 0–4. Both columns are submission-to-device times from PortAudio's scheduled output timestamp. The first column is when the first source PCM frame, zero or not, was scheduled (`phases.first_pcm_dac_ms`). The second is when the first nonzero sample was scheduled (`latency.scheduled_dac_ms`).

| Trial | First source PCM scheduled at device (ms) | First nonzero source PCM scheduled at device (ms) |
|---|---:|---:|
| 1 | 152.09 | 332.06 |
| 2 | 147.84 | 327.84 |
| 3 | 147.86 | 327.88 |
| 4 | 194.56 | 374.50 |
| 5 | 196.01 | 375.95 |

All five reached Played with no reported driver underflow. Scheduled device time
uses PortAudio's output timestamp, not an acoustic recording. Approximately
180 ms of model-generated leading digital silence separates the two readings;
that silence was preserved. Neither these observations nor earlier inference-only
numbers demonstrate the requested under-150-ms end-to-end target.

Earlier phase measurements found about 620 ms opening the device, while device
refresh itself cost about 2 ms. Preparing the physical stream removes that startup
cost from warmed submissions. Direct model-only measurements around 94–97 ms
were insufficient predictors: full-path inference varied roughly 113–154 ms.
An exploratory sentence-stream run overlapped test-suite setup and is excluded
from acceptance evidence. A preliminary first-PCM probe also observed a stale
previous-session playhead; it was replaced by a session-gated probe before these
final readings. No favorable retry was substituted for this baseline distribution.

## Leading-zero playback optimization

Playback now skips only an initial run of exact PCM zeros. The scan is bounded
to at most one second of buffered PCM per callback and never performs disk I/O.
The original WAV remains byte-for-byte unchanged; the source playhead reflects
skipped frames and playback evidence records `skipped_silence_frames`. An explicit
nonzero seek retains silence at the selected position. Pauses within speech,
including silence arriving in a later engine chunk, are retained.

The new boundary test was observed red before the option existed
(`/tmp/stream-leading-silence-red.log`). Mutations disabling skip or applying it
to a nonzero seek failed their assertions. A mutation that also trimmed later
engine chunks initially survived a single-buffer example; the later-chunk
schedule was added and observed red (`/tmp/stream-trim-later-red.log`). All
restored tests passed in the 634-test full run.

Five new isolated hardware trials with this optimization reached first nonzero
scheduled device output at **200.37, 205.36, 196.15, 196.01, 193.85 ms**. All
reached Played without a reported driver underflow. The raw JSON retains the
previous measurements as `baseline_trials`; `trials` holds this newer run.
This removes the leading-zero delay but still does not meet 150 ms.

The remaining inference slowdown reproduces in a process with no audio device:
consecutive calls took about 93–94 ms, while calls after 3.65 seconds idle took
160–165 ms. Smaller Python scheduling intervals, lower device latency, changing
thread QoS, a small GPU wakeup operation, and temporary float16 weights did not
give a reliable improvement. None of those experimental changes were adopted.
The QoS experiment followed Apple's
[pthread task-priority API](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/PrioritizeWorkAtTheTaskLevel.html).
No system power settings were changed. Compiling ALBERT and its projection layers
also did not reliably improve idle latency and added initial compilation cost;
that experiment was not adopted. A profile of identical calls without an audio
device measured 98 ms immediately warm and 155 ms after idle, with increases in
both Python-side preparation and native model evaluation. This narrows the next
investigation to model execution after idle rather than callback thread scheduling.
The physical output for these trials was Studio Display Speakers (48 kHz native,
23.625 ms suggested low output latency); the transport used 24 kHz mono PCM.

## Final lifecycle review

Output preparation and model warmup now report independent outcomes. A seeded
output failure originally reported the model as failed; the corrected test uses
the snapshot contract and observes `ready` after the output attempt. The first
harness mistakenly queried `status`, which does not contain `runtime`; that
KeyError is not counted as regression evidence. The valid observed red is
`/tmp/stream-output-readiness-red.log` (`failed` versus `ready`).

Streaming document publication now commits child metadata, aggregate duration
and producer ownership together. A seeded parent-duration write failure initially
left the child pointing at an uncommitted artifact; it now rolls back both live
and durable state (`/tmp/stream-composite-atomic-red.log`). Similarly, a failed
readiness write originally stranded completed standalone and composite clips in
Synthesizing. Readiness, child/parent state and the unfinished-generation record
now commit together, with notifications only after commit. Both observed-red
cases are in `/tmp/stream-readiness-transaction-red.log`.

## Follow-ups and limits

- Resolve remaining inference latency and variability in issue #33, without
  substituting transport-only latency. This is explicitly deferred by the user.
- README and architecture documentation describe automatic capability-based
  streaming, provisional readiness, recovery and measured limitations.
- Real long-pause/microphone-interruption, physical route-change, and acoustic
  acceptance remain outside the controlled callback tests. Issue #25 is not
  claimed fixed or closed.

## Main reconciliation and dependency gate

The streaming feature was replayed onto reviewed main `6482b49`, preserving
export draining before Store shutdown and platform composition boundaries.
Its integrated stage passed 689 Python tests. The subsequent combined stack
passed 793 Python tests and 142 Swift tests with warnings as errors (historical: the whole eight-PR stack, Swift PRs included).

Hosted run `36734083447` then failed the strict dependency audit: locked
`urllib3 2.7.0` had CVE-2026-97687 and CVE-2026-97689, both listing 2.8.0 as
the fixed release. The pin and archive hashes were updated only for urllib3.
No advisory was ignored and the failed run was not retried unchanged.
The updated combined all-extras graph passed strict PyPI and pinned-source
auditing: 164 dependencies, 189 SBOM components, 164 license records, zero
known findings; the existing espeakng-loader license classification stays open.
The combined 793 Python tests passed again (14.43 seconds wall clock).
Raw audit receipts are retained locally under `.git/codex-scratch/integration-audit`;
the failed hosted artifact retains the original advisory evidence.

## Integration with the subsequent mainline lifecycle/replay audit

The stack was refreshed onto `954807b` after benchmark PR #47 exposed the old
stack's PyJWT audit failure. Mainline already supplies patched PyJWT 2.15.1,
exclusive daemon ownership, request-independent reload, silent Ready recovery,
final-playhead shutdown capture and durable generation identity. Integration
retains those contracts rather than restoring the pre-audit versions.

Streaming shutdown holds transport and delegates final device retirement to the
mainline controller stop boundary before closing spools. The duplicate later
stop call is removed. Model registry integration retains daemon-owned reload
and synthesis exclusion even when the waiting request is cancelled.

A compatibility regression in the provisional merge was observed red in both
single-clip and document publication: after streaming publication and audio
forgetting, the public stored item returned `(None, None)` for audio path and
generation identity instead of `(None, work.id)`. The streaming publication
transaction now saves the generation identity alongside path/duration, before
removing the unfinished-job record. `test_stream_publication_retains_generation_identity`
passes both cases. This extends the feature to preserve mainline's durable
provenance contract; it changes no measured historical baseline.

Focused integration validation: 16 streaming-lifecycle, delayed-release shutdown
and cancelled-reload tests passed. The two identity failures above are the
red-before-fix and falsification evidence for the new public-data assertion.

## Streaming review regressions

Change kind: bug fixes within the streaming feature. Three medium boundary
tests in `tests/test_streaming_review.py` were observed red on `e00bfb1` before
production edits, then passed with the fixes:

- Rewind while synthesis publishes during device retirement used the old
  pathless row and tried to open the artifact ID as a filename. A controlled
  release gate demonstrates the interleaving; rewind now rereads the durable
  row after retirement and opens the published WAV at zero.
- An initially unreadable route identity was adopted but discarded by the
  streaming poll loop. A scripted device identity sequence failed to reopen
  before its liveness deadline; polling now uses the adopted identity.
- Reusing a sink carried the first clip's underflow count into the next clip's
  playback evidence: observed `[[1], [1]]`, expected `[[1], [0]]`. Each stream
  now resets its route debounce state and underflow counter.

The oracles observe the playback port's selected artifact, route reopening,
and actual per-clip JSONL evidence. Owned callback/device doubles avoid audio
hardware. These red results calibrate the added assertions; deletion criteria
are recorded beside the tests. The broader proposed synchronous registry
lookup/retain race was not reproduced: publication and lookup currently run
on the same event loop without an intervening await. No new registry
concurrency contract is claimed. These fixes do not establish the cause of
the reported acoustic popping.

Validation after review fixes: Ruff check/format and mypy passed; all 771
Python tests passed (260 small, 511 medium; 12.75 seconds wall clock).

## Merge with main and review round (Code Lawyer, 2026-10-01)

Change-kind: bug fix. `origin/main` was merged at `6428b58`. It brought #56 (installer), #57 (soft stream close and open, device-rate host block) and #64 (playhead versus heard position). The only textual conflict was the testing profile, and both sides were kept. The full suite passed on the merge: 785 passed, 2 skipped.

The merge was clean as text but not as behaviour. With output prepared, every compatible 24 kHz mono WAV plays through the callback path, and #57's soft close and open existed only in the file path. The rows below port them to the callback path. They also fix the review threads that were still valid. Each regression test was run red on its parent commit, then green on the fix. The `tests/test_streaming_soft_transport.py` oracle is the [soft-stream-close receipt](2026-09-30-soft-stream-close.md).

| Issue | Regression test | Parent (red) | Red output |
|---|---|---|---|
| A callback close ramped the last written sample over 5 ms, the stop ramp #57 retired | `test_stop_fades_the_upcoming_source_then_holds_silence_before_closing` | `6428b58` | 479 of 480 fade samples differ from the next 20 ms of source under a raised cosine (first: 0.2093 against 0.2057) |
| With less source left than the fade, the close did not hold the last sample | `test_stop_near_the_end_holds_the_last_sample_under_the_fade` | `6428b58` | 479 of 480 samples differ; mutation padding zeros instead of holding: 379 of 480 differ |
| A renderer opened mid-clip used the 5 ms linear underrun ramp, not a 20 ms raised-cosine fade-in from zero | `test_a_mid_clip_open_fades_in_from_silence_at_the_held_position` | `4caca36` | 478 of 480 differ (sample 5: 0.0062 against 0.00004; worst 0.189) |
| A stop during that fade-in closed from full gain | `test_a_stop_during_the_fade_in_closes_from_the_gain_reached` | `4caca36` | 478 of 480 differ; mutation forcing an opening gain of 1.0: 478 of 480 differ |
| A generation failure in a streamed child left that child Cancelled with no error (CodeRabbit) | `test_generation_failure_fails_the_streamed_segment_with_its_error[Ready, Playing]` | `9095255` | `(Cancelled, None) != (Failed, 'seeded engine failure')` in both cases |
| Recovery requeued a streamed child the listener had skipped before a crash (CodeRabbit) | `test_recovery_keeps_a_skipped_streamed_segment_skipped` | `d557e58` | `Queued is not Skipped`: the listener would hear a skipped chunk again |
| The streaming shutdown hold re-held a microphone hold and erased its durable reason (CodeRabbit) | `test_shutdown_keeps_the_reason_for_a_microphone_hold` | `f234c91` | `the restarted daemon lost why it is silent`: `interrupted_at` was `None` |

Refactor, with no red needed: both engines now frame and quantize through one `aitts.streaming.pcm16_frames` helper (CodeRabbit). The existing exact-byte tests are the characterization: `test_kokoro_yields_bounded_pcm_before_requesting_next_inference_result` covers the 32767 and -32768 boundaries and truncation, and the MLX chunk-length test covers the same for MLX. Both pass unchanged.

Host block on the callback stream, approved by the user on 2026-10-01: the callback stream asked for `blocksize=240`. The HAL buffer equals the requested block in device frames, so that was 5 ms at 48 kHz, shorter than the 13.4 ms stall behind the app-switch pop that #57 fixed for file playback. `_open_pcm_callback_stream` now reuses main's `_host_block_frames(device_rate)`, with the device rate from `sd.query_devices(kind="output")["default_samplerate"]`.

The cost was measured on this Mac on 2026-10-01 with silent output: a 24 kHz callback `sd.OutputStream` on the 48 kHz built-in speakers. With `blocksize=240` the HAL buffer was 240 frames (5 ms) and `stream.latency` was 44.8 ms. With `blocksize=1024` the HAL buffer was 1024 frames (21.3 ms) and `stream.latency` was 77.4 ms. The cost on the callback path is therefore about +33 ms of output latency. It is not the 0.13 s that #57 measured for the blocking file stream (130.1 to 248.1 ms there). The 194–205 ms first-audio readings above were taken with the 240-frame block and have not been re-measured.

| Issue | Regression test | Parent (red) | Red output |
|---|---|---|---|
| The callback stream requested a 240-frame block, a 5 ms host buffer at 48 kHz, below #57's 21.3 ms | `test_callback_stream_requests_a_host_buffer_longer_than_an_observed_stall[44100, 48000, 96000, 192000]` | `7391f74` | requested 5.4, 5.0, 2.5 and 1.2 ms, against at least 21.3 ms |

With host-sized blocks (941 or more frames at 24 kHz for any device of 44.1 kHz or more), the soft-close fade cap "20 ms or one callback block" always gives the full 20 ms. `test_native_pause_spools_to_completion_and_resumes_without_advancing_held_time`, which needs a pause to end within one 240-frame test block, passes unmodified.

### Second CodeRabbit round

| Issue | Regression test | Parent (red) | Red output |
|---|---|---|---|
| Kokoro's stream adapter wrapped its own `SynthesisError` in a second one | `test_invalid_stream_samples_raise_the_adapter_error_unwrapped` | `0ba2b01` | `the adapter's own SynthesisError was wrapped in a second one` |

Authoritative validation for this head: **798 Python tests passed, 2 skipped** (263 small, 535 medium). Ruff check, ruff format, and mypy (140 files) are clean. This PR's own diff changes no Swift. The merged-in main Swift sources pass 140 Swift tests at merge `0ba2b01`.

A mutation that drops the 100 ms close silence fails the first test with `the stream closed before 100 ms of silence` (544 silent frames, not 2400). The fade spans min(20 ms, callback block), so a 10 ms test callback still ends its pause block at zero, as `test_native_pause_spools_to_completion_and_resumes_without_advancing_held_time` requires. A prepared device keeps playing silence after the session, so only a session that closes its own stream adds the 100 ms of silence.
