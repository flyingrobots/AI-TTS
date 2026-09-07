# The life of one utterance

This is the walkthrough the rest of the design docs assume. `architecture.md`
says what the parts are and why; this says what actually happens, in order,
when an agent asks for one sentence to be spoken. Everything below is named by
module and symbol rather than by line number, so it stays true as the files
move.

Read it once and the rest of the codebase stops being a maze: nine of the
twelve modules appear here, in the order they run.

## 0. The shape of the thing

Two queues, not one. That distinction is the single most load-bearing idea in
the system, and every stage below belongs to one of them.

- The **synthesis queue** is parallel. Several workers may render audio at
  once, and throwing more workers at it makes it faster.
- The **playback queue** is serial and real-time. Exactly one utterance may
  hold the audio device, because two voices at once are unintelligible — the
  original defect that motivated the whole project.

An utterance is therefore *always* waiting for one of two different things,
and `metrics` reports those two waits separately for exactly this reason
(`aitts.application.metrics`).

## 1. A client says something

```sh
ai-tts say "the build is green" --source claude-code --voice bm_daniel
```

`aitts.cli` parses the arguments and hands a request dict to
`aitts.client.DaemonClient`, which connects to the Unix socket and writes one
line of JSON.

The socket is the boundary, and it is a socket rather than a port on purpose:
a Unix socket cannot be accidentally exposed to a network. It is mode `0600`,
so the operating system's own permission check is the authentication.

## 2. The daemon reads one line

`aitts.ipc.IPCServer` reads the connection line by line. Two limits guard it,
and both are deliberate: the stream reader is constructed with a byte limit,
*and* the length is checked explicitly after reading. The first stops an
unbounded line being buffered at all; the second stops a line that arrives
exactly at the boundary being accepted. Anything over `MAX_JSONL_LINE_BYTES`
is refused rather than truncated, because a truncated JSON line is not a
smaller request — it is a different one.

The parsed payload goes to `Daemon.dispatch`, which is a flat table from `op`
name to handler. An unknown op is an error, never a no-op.

## 3. Submit: everything is decided here

`Daemon._op_submit` is where an utterance acquires every property it will ever
have. In order:

1. **Text** must be a non-empty string.
2. **Sensitivity** defaults to `confidential`. This fails *closed*: a caller
   that says nothing gets the most restrictive handling, because the cost of
   guessing wrong in the other direction is client-confidential text reaching
   a remote engine. It is assigned once here and never changes — an utterance
   cannot be reclassified after submission, or the same id would mean two
   different things at two times and history could not say which.
3. **Voice** is resolved by `aitts.voice_registry.VoiceRegistry.resolve`. The
   caller's `--voice` is a *preference*, not a decision: the listener's own
   assignment outranks it, a source keeps whatever voice it already holds, and
   a source the daemon has not heard from claims one nobody else has. The
   requested voice is validated *before* the register can record it — claiming
   first meant a misspelled voice became a durable claim, and since a held
   voice outranks later requests, that source could never speak again.
4. **Speed** comes from the request or the settings table, through the one
   parser in `aitts.settings` so the submit path and a settings write cannot
   disagree about what is valid.
5. **Segmentation** runs next. `aitts.segmentation.prepare_speech_segments`
   turns the text into the chunks that will actually be spoken, discarding
   what should not be read aloud. Text that reduces to nothing speakable is
   refused here rather than queued and silently skipped.
6. **The row is written.** `aitts.store.Store.submit` creates the utterance
   already in `Queued`, plus one child row per chunk when the text was split.
   `Urgent` inserts at the head of the plan; `Normal` appends.

The receipt names the voice that will actually speak, not the one that was
asked for, because the register can overrule the request and a client that is
not told has no way to know.

It also carries `accepting_speech`, `playback_held` and a plain-language
`submission_guidance`. A paused queue is *not* backpressure: speech is still
accepted and spooled. Agents given only "paused" reliably interpret it as
"stop submitting", which is the opposite of what a hold means here.

The pool is nudged, and the call returns. Nothing has been synthesized and
nothing has been heard.

## 4. Synthesis: parallel, and interruptible only by cancellation

`aitts.synthesis.SynthesisPool` runs a fixed number of workers.

Each worker calls `Store.claim_for_synthesis`, which is one SQL statement that
atomically picks the earliest unclaimed unit — a whole utterance, or one chunk
of a split one — and marks it `Synthesizing`. Atomicity is the point: two
workers must never claim the same unit, and the database is the arbiter rather
than a lock in Python.

With nothing to claim, a worker parks on an event with a short timeout instead
of spinning. It is woken by `notify()`; the timeout is only a safety net.

The claimed work goes to the engine on a worker thread
(`asyncio.to_thread`), because synthesis is CPU-bound and would otherwise
block the event loop that is also serving the socket and driving playback.

`aitts.engines.kokoro.KokoroEngine` renders the audio. Two things about it
matter more than the model:

- **Assets resolve from the local cache first.** Left to its defaults the
  upstream package asks the model host for its config, its weights and *each
  voice pack* on every load. For a daemon whose text is client-confidential
  that is metadata about confidential speech leaving the machine — the request
  names the exact voice and the moment it spoke — and it makes the daemon
  useless offline. `KokoroAssets` only fetches a genuinely absent file, and
  the *first* run reports what it is fetching so the wait is legible.
- **The pipeline is handed a file path, not a voice id.** Given a bare id it
  re-resolves the pack through the model host on every load. This is the whole
  network fix, and it is one line.

The result is written to a candidate path, validated, and then *published*
(`aitts.application.artifacts`) — final publication and the durable owner
record happen in one event-loop turn, so the cache purge that also runs on
that loop can see either an invisible candidate or a protected published
artifact, never an unowned final WAV between the two.

An utterance cancelled while its audio was rendering has its result discarded
on completion: the engine cannot be aborted mid-render, so the work finishes
and the output is thrown away.

The utterance is now `Ready`, and the wait that just ended was the parallel
one.

## 5. Playback: serial, and owned by the listener

`aitts.playback.PlaybackController.run` is a plan loop. Each pass:

- If nothing holds the device and playback is not held, take the earliest
  `Ready` utterance and begin it — or begin its first unfinished chunk.
- If something holds the device but the sink is no longer active, decide what
  that means: a terminal document is released so the queue behind it can move,
  and a document with another `Ready` chunk continues into it.

Then it clears its wake event and waits, backing off from 100 ms toward 2
seconds. `notify()` is the real signal; the timeout is a safety net, and the
back-off is what keeps an idle daemon from querying SQLite ten times a second
forever.

Beginning playback transitions the row to `Playing`, starts the sink, and
spawns a watcher task. The second wait — `Ready` to `Playing` — is the serial
one, and no amount of parallelism shortens it.

### The sink, and the device it does not trust

`SoundDeviceSink.start` hands the file to a daemon thread. Inside
`_play_blocking`, each pass through `_play_on_current_device` owns exactly one
output stream, and a pass ends at the end of the file, on stop, or when the
listener moves the system default output.

That last case is the fix for the defect that started this: the audio library
resolves its device list once, when it initializes, and answers every later
query from that snapshot. A daemon that outlives a hardware change keeps
speaking to a device the listener has already left. So the sink reads the
default output *live from CoreAudio*, rebuilds the library's snapshot before
each stream with no stream open (re-initializing invalidates live streams),
and reopens on the new device at the frame already reached — nothing repeated
and nothing dropped. A device change is confirmed across two consecutive
readings, and an unreadable identity counts as *unchanged*, because tearing
down a working stream over a transient failure is worse than being slow to
follow.

### The listener can interrupt

`aitts.input_interrupt.InputInterruptWatcher` polls whether anything is
capturing audio input. The reading is coarse and sticky — it says a device is
open, not that anyone is speaking, and dictation software holds the device
open for minutes after a recording — so only the **cold-to-hot edge** counts
as the floor changing hands. A level-triggered reading would re-raise the hold
immediately after every Resume, which is indistinguishable from Resume being
broken.

The hold stays until the listener says otherwise, or releases itself when the
input goes quiet if they asked for that. An armed resume is deliberately not
gated on the feature switch: it exists because they asked for it, and dropping
it on a later toggle would leave playback held with nothing to explain it.

## 6. The end, and what is kept

The watcher task awaits the sink and turns its result into a state change:

- Reached the end: `Played`.
- Stopped by someone: nothing — whoever stopped it owns the state change.
- Failed: `Failed`, with `played_ms` set to the position actually reached, and
  the error prefixed `playback device error:` so metrics can count a device
  failure apart from an ordinary cancellation.

Every transition fires `Daemon._on_transition`, which does three things:
records the timing in `MetricsRecorder`, logs a `trace=` token so this clip
can be followed through the log, and broadcasts `state_changed` to every
subscriber so the menu bar updates without polling.

When a terminal utterance's audio is no longer needed, `enforce_cache_limit`
brings the cache back under its configured ceiling. History is kept
permanently and by design; only the *audio* is evictable.

## 7. What the log will and will not tell you

The diagnostics are bounded structurally, not by convention. Call sites use
literal `event=` templates and may interpolate only a reviewed allowlist of
non-content values — a test enforces this by scanning the package. Speech
text, source labels, selected-document paths, cache paths, exception messages
and tracebacks do not reach the persistent log.

The one thing that *is* correlated across every stage is the `trace=` token: a
short prefix of the utterance's identifier, derived rather than stored. It is
allowed in precisely because the identifier is a random uuid — it names a row
and reveals nothing about its content.

So the log answers "where did this clip get to" and "what class of failure was
it", and deliberately cannot answer "what did it say".

## Where to look next

| If you are changing... | Start in |
| --- | --- |
| what may be spoken by whom | `aitts.model` (`Sensitivity`), `aitts.engine` (`eligible_engine_names`) |
| the wire contract | `aitts.ipc`, `aitts.application.schemas` |
| queue order or state rules | `aitts.store`, `aitts.model` |
| how text is split | `aitts.segmentation` |
| the engine | `aitts.engines.kokoro`, `aitts.engine` (the port) |
| device ownership or transport | `aitts.playback` |
| settings validation | `aitts.settings` |
| which client gets which voice | `aitts.voice_registry`, `aitts.application.voice_assignment` |
| interruption behaviour | `aitts.input_interrupt`, `aitts.application.input_activity` |
| the menu bar | `clients/menubar/Sources/AITTSMenuBar/` (one file per surface) |
