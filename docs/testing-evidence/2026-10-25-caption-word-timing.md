# Caption drift and word timing

Change-kind: feature (word timing, `timings` op, `playback_position` events),
with one bug fix (menu-bar captions drift from the voice) built on it.

## Diagnosis: why captions drift

Captions picked a phrase cue by assuming speech time is proportional to
letters: cue *k* starts at `position / duration × total weight`, where the
weight is one per letter or digit plus 6 for `.!?;:` and 3 for `,–—`. Four
causes, measured on 2026-10-25 on Apple Silicon, `bm_daniel` at 1×:

1. **Spoken time is not letter count.** Numbers, symbols and abbreviations
   are spoken far longer than they are written (`$3,450.75` is "three
   thousand four hundred fifty dollars and seventy-five cents"). Pause lengths
   vary by engine and sentence. Error grows along the clip.
2. **A streaming clip has no duration until generation finishes.** Kokoro and
   Kokoro MLX play from the first PCM. `active_segment.duration_ms` is `null`
   until the WAV is published, so the caption stays on the first cue for
   the whole generation time, then jumps. The jump is 3.7 s for a 40 s clip on
   Kokoro, 2.2 s on MLX, and longer for 180–220-word document chunks.
3. **Abbreviation periods split cues.** `Dr.`, `p.m.` and `Jan.` ended a
   cue, giving "In 1995, Dr." / "Smith paid …" and "on Jan." / "5th.". The
   error from cause 1 then shifts every later cue.
4. **The clip begins with silence.** It lasts 225–285 ms on Kokoro. The
   proportional model starts the first cue at 0.

Ruled out: client staleness. A read-only `snapshot` round trip to the live
daemon took 2.6 ms median (4.0 ms max, 15 requests, 54 KB reply), so the menu's
`observedAt` lag is negligible. Not addressed: output-device latency. The
reported position is the source frame handed to the device. A word is
therefore heard later by the stream's output latency. That is about 45–77 ms
on built-in speakers (see CHANGELOG) and more on Bluetooth.

### Measurements

The reference is Kokoro's own token times. They are validated against audio
pauses: on the 141-word passage, sentence-start tokens precede the pause end
by 60 ms mean, 80 ms max (n = 8). All errors are absolute cue-start errors
in milliseconds.

| Passage (clip) | Engine | Today's caption model, vs Kokoro tokens | vs audio pauses |
|---|---|---|---|
| prose, 59 words (16.6 s) | Kokoro | mean 200, max 369 (n = 9) | — |
| numbers, 29 words (16.4 s) | Kokoro | mean 611, max 1,382 (n = 7) | — |
| long, 141 words (40.2 s) | Kokoro | mean 472, max 1,070 (n = 18) | mean 411, max 930 (n = 8) |
| long (40.2 s) | Kokoro MLX | (same audio timing ±25 ms) | mean 421, max 943 (n = 8) |
| prose (20.4 s) | Chatterbox | — | mean 599, max 2,034 (n = 6) |
| long (31.1 s) | Chatterbox | — | mean 1,776, max 2,856 (n = 8) |

Scripts and raw JSON are session scratch (see the end of this receipt). The
passages are fixed, generated public text.

## What changed

- **Engine timing.** Kokoro (torch) reports each token's interval from its
  duration predictor: `KPipeline` `start_ts`/`end_ts`, offset by the audio of
  earlier pipeline results. Kokoro MLX computes the same durations inside
  `forward` and does not return them. For the length of one locked call, the
  adapter observes (but does not replace) the duration projection and the G2P.
  It applies the upstream `join_timestamps` algorithm, ported, and keeps the
  marks only when `Σ frames × 600` equals the chunk's sample count exactly.
- **Estimate.** Chatterbox, the OpenAI-compatible adapter, and old workers do
  not report timing. For them, word weights count digits ×3.5 and symbols ×4.
  Sentence boundaries, then clause boundaries within each sentence, are
  anchored to pauses detected in the rendered audio, using an order-preserving
  minimum-cost match. The result is labelled `estimated`.
- **Unspoken text stays untimed** ([#99](https://github.com/flyingrobots/AI-TTS/issues/99)).
  Words after the last engine mark get no time; they are not stamped at the
  clip's end. If an estimate's audio is too short for its text, only the
  prefix that fits at a nominal rate is timed. "Too short" means an apparent
  rate above 36 weight units/s at the clip's generation speed; measured 1×
  speech runs 13–24. A truncated render therefore does not caption words it
  never said. A client sees `null` times with `complete: true`.
- **Persistence.** Timings are stored in `artifact_timings`, keyed by the
  generation artifact identity. A cached replay or rewind that reuses audio
  therefore reuses its timings. Rows are pruned with their last referencing
  history row and at startup.
- **Live marks.** While a clip is generating, the marks so far are served from
  memory. A listener can follow a clip that started before it finished
  rendering. Marks precede the PCM they describe.
- **Protocol.** See architecture §5: the `timings` op and the opt-in
  `playback_position` subscription (`v: 1`), with code-point or UTF-16
  offsets into the exact submitted text, through segmentation and Markdown
  projection.
- **Worker protocol 1, extended compatibly.** The daemon adds
  `"timings": true` to `synthesize`/`stream`. A worker that understands it
  replies with `marks`; a worker installed before this change ignores it.
  The clip then gets an estimate. A runtime gets engine timing only after
  its adapter snapshot is reinstalled (model setup **Retry**/reinstall); no
  manifest version changes.
- **Captions.** The menu fetches the active clip's timing and shows the cue
  holding the word whose start was most recently reached. This needs no
  duration, so streaming clips caption correctly. Without timing (an older
  daemon), the proportional estimate remains. Abbreviation periods no longer
  end a cue.

## Accuracy after the change

**End to end** through an isolated daemon (private temp home and socket,
silent fake sink, nothing played aloud), with each installed runtime's venv
and assets and this branch's worker adapter:

| Engine | Timing | Word starts vs Kokoro (torch) tokens | Sentence starts vs pause ends | Offsets |
|---|---|---|---|---|
| Kokoro | `engine` | 0 ms, 229 of 229 words | mean 60–66, max 80 (n = 15) | exact, all words |
| Kokoro MLX | `engine` | mean 0–22, max 26 (229 words) | mean 59–66, max 80 (n = 15) | exact, all words |
| Chatterbox | `estimated` | n/a (no word-level reference) | 0 by construction (anchored) | exact, all words |

On Kokoro and MLX, 85 of 141 words of the long passage were available live,
before generation finished.

**Estimator accuracy.** Its own error was measured on Kokoro audio, where the
engine's tokens are the reference. This is the fallback used for Chatterbox:

| Passage | Word starts | Cue starts | Today's cue starts |
|---|---|---|---|
| prose | mean 111, p90 235, max 272 | mean 68, max 161 | mean 200, max 369 |
| numbers | mean 152, p90 437, max 503 | mean 179, max 503 | mean 611, max 1,382 |
| long | mean 131, p90 240, max 443 | mean 107, max 235 | mean 472, max 1,070 |

Without pause anchoring the estimate is far worse (long: word-start mean
715 ms). The anchor is load-bearing. For Chatterbox, word-level accuracy is
unmeasured. Its pauses are longer and more variable than Kokoro's, so expect
errors at least as large as the table above between pauses.

## Tests and falsification

New Python tests (47): `tests/test_timing.py` (36 small),
`tests/test_store_timings.py` (2 small), `tests/test_engine_timing_adapters.py`
(3 small), `tests/test_managed_timings.py` (2 medium), and
`tests/test_word_timing_daemon.py` (4 medium, including a real Unix-socket
follower in UTF-16). New Swift tests (6): 4 caption tests and 2 adapter tests.
The oracle for times is the engine's own duration prediction, or owned
synthetic audio with known silences. The oracle for offsets is exact
substrings of the submitted text.

Each load-bearing mutation below was applied alone and its named test run.
Every one went red, and every mutation was reverted:

- pause anchoring disabled (`split` returns the whole piece): the estimate
  anchor test fails;
- pipeline-result offset dropped in the Kokoro adapter: the offset test
  fails;
- abbreviation rule removed: the sentence-boundary test fails;
- live marks not recorded: the streaming-clip test fails on its live word;
- front-matter cursor skip removed: the socket test fails at its body-offset
  assertion (`source_start`);
- UTF-16 conversion bypassed: the socket test's emoji assertion fails;
- timing pruning removed: the store test fails;
- worker-mark validation bypassed: the malformed-marks tests fail;
- MLX sample-count guard removed: the mismatched-observation test fails;
- mark coverage check removed: the foreign-marks test fails;
- truncation rate check removed: the short-audio test fails;
- unspoken suffix stamped at the clip end: the untimed-suffix test fails.

**Bug fix, red on the unfixed caption code.** The parent's `CaptionCueTrack`
(`c081d50`) was restored behind the new initializer, with timing ignored. 3
of 10 caption tests failed (7 assertions): the abbreviation cues ("In 1995,
Dr." / "Smith paid …"), the timed cue at 6,600 ms, and incomplete timing. The
last one reproduces cause 2: with no duration, the parent returned the first
cue at 13 s. All pass with the fix.

## Validation

On the final candidate, based on `main` at `c081d50`:

- `ruff check`, `ruff format --check` and `mypy` (209 files): clean.
- Python: 1,184 passed and 2 skipped, out of 1,186 collected (the 1,137
  existing plus 47 new). Small tier 1.16 s CPU, medium tier 16.77 s CPU, both
  within budget.
- Swift: 193 tests, 0 failures, 0 warnings.
- Real engines: three runs per engine, each under the `host/gpu/` workstation
  lock. Diagnosis used direct adapter calls. The end-to-end check used an
  isolated daemon instance; no installed daemon, LaunchAgent, socket or
  runtime was modified.

Not done: no installed-app or acoustic check, and no listening acceptance.
Installed runtimes report `estimated` timing until their model setup is
rerun with this adapter. MCP tools do not expose `timings` yet.

Measurement scripts (`measure_drift.py`, `analyze_drift.py`,
`eval_estimator.py`, `mlx_probe.py`, `e2e_timing.py`, `falsify.py`) and
their raw JSON were session scratch, about 10 MiB with the WAVs, and were
not committed. The tables above are the retained record.
