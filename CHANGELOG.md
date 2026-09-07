# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The listener's voice takes the floor.** Playback stops when something
  starts using the microphone and then waits, so dictating to an agent works
  as a conversation instead of a shouting match. The platform reading is
  coarse and sticky — dictation software holds the input open for minutes
  after a recording — so the hold is raised on the cold-to-hot edge and never
  re-raised, which is what makes Resume stick. The popover explains the hold
  and offers Resume, resume-when-the-mic-is-cold, and Skip.
  `input_interrupt_enabled` and `input_interrupt_resume` configure it.
- **Chunk stepping.** Next and previous chunk join the transport for
  documents split into a nested clip queue, as `next_segment` and
  `previous_segment` ops and as buttons that appear beside Skip only when the
  current clip has chunks. Forwards gives up one chunk; backwards replays the
  one before from its start.
- **A window that reads a clip in full.** Captions show one chunk and the
  popover a few lines; the current clip and every History row now open their
  untruncated text in a resizable window, rendered from the snapshot rather
  than written to a file.
- **A per-client voice register.** Each `source` holds its own voice, recorded
  on first contact and persisted, so two agents cannot end up sharing one —
  the store showed three sharing `bm_daniel`. Settings lists the mapping and
  lets you reassign it; your assignment outranks the client's request.
  `voice_assignments` and `assign_voice` expose it on the wire.
- **MCP parity for every new operation.** `next_speech_chunk`,
  `previous_speech_chunk`, `resume_speech_when_input_idle`,
  `list_speech_voice_assignments` and `assign_speech_voice` join the tool
  surface, so the architecture's promise that nothing the tray can do is
  unavailable to an agent holds again. The tool-count assertion now tracks the
  declared inventory rather than a literal that had to be edited in step.
- **Thirteen more voices**, for 41 total: Spanish, French, Hindi, Italian and
  Brazilian Portuguese alongside the English sets, each verified by
  synthesizing audio with the dependencies already installed. Settings groups
  the catalog by language. Japanese and Mandarin remain out, pending a
  deliberate supply-chain decision about `misaki[ja]` and `misaki[zh]`.
- **Design and project foundation**: feature breakdown, architecture, engine
  evaluation, technology choices, menu-bar UI mockups, consolidated design
  decisions, Apache 2.0 licensing, contribution and security guidance.
- **Daemon** (Python 3.12, asyncio): SQLite-backed store, utterance state
  machine with named transitions, parallel synthesis pool, strictly serial
  in-order playback controller that solely owns the audio device, and
  NDJSON-over-Unix-socket IPC (mode 0600) with typed errors and event
  subscription. Restart recovery re-queues interrupted synthesis and never
  resumes speaking on its own.
- **Sensitivity routing**: every utterance carries `public` / `internal` /
  `confidential` (fail-closed default `confidential`); non-public text can
  never route to a non-local engine.
- **CLI** (`ai-tts`): say/wait/list/history/pause/resume/skip/rewind/cancel/
  clear/status/voices/settings/daemon, plus next-chunk/prev-chunk,
  resume-when-idle, voice-map and assign-voice. Exit 0 means accepted onto the
  queue; `say --wait` and `wait` exit 0 only for Played.
- **Kokoro-82M engine adapter** via the reference `kokoro` package, one warm
  pipeline per language.
- **Snapshot protocol**: one daemon request returns status, both queues, the
  merged playback plan, history, voices and settings; status carries live
  playback position and history items carry completion time.
- **Menu-bar app** (Swift/SwiftUI, `clients/menubar`): custom animated template
  tray icons; event-driven refresh with reconnect; a pinned current-playback
  card; unified Queue/History tabs; exact playback ordering with inline
  synthesis state and drag reordering; removable and clearable queues/history;
  priority-aware history re-queue; voice previews; Settings; and transport
  controls.
- **Local document picker**: Queue can enqueue UTF-8 plain text, Markdown, and
  text-bearing PDF files. The app extracts only a user-selected file, submits
  its text through the existing confidential queue boundary, and gives explicit
  guidance for locked or image-only PDFs. Acquisition is bounded at 512 KiB for
  text/Markdown and at 32 MiB, 500 pages, and 512 KiB of extracted text for PDF.
- **Infrastructure**: pytest suite written before the implementation, ruff
  `--select ALL` and `mypy --strict` clean, git hooks in `scripts/hooks/`,
  GitHub Actions CI (Python + Swift), launchd agent plist, and an all-extras
  dependency job that audits hashed lock exports, emits a CycloneDX SBOM,
  inventories licenses, cross-checks every retained report, and preserves the
  evidence for 14 days.
- **Agent-native MCP server** (`ai-tts-mcp`): a stdio-only, 100% JSONL tool
  surface for enqueue, truthful status, unified Queue/History reads, voices,
  playback controls, cancellation, priority-aware requeue, and queue clear.
  A transport-neutral `SpeechServicePort` and immutable public schemas sit
  between the MCP and Unix-socket encoding adapters.
- **Binding testing standard**: repository-wide rules for contract boundaries,
  named oracles, assertion calibration, deterministic generated evidence,
  explicit size classes, hermeticity, and trustworthy CI signals.
- **Recovery fault campaign**: deterministic post-commit crash injection at
  every state-repair boundary, proving repeated restart converges with queued
  text intact and no persisted item left `Playing`.
- **Deterministic playback scheduler**: explicit plan and sink-result
  checkpoints for exhaustive ordering of the current watcher/control race.
  Playback tests now use condition witnesses instead of fixed-duration sleeps.
- **Checkout-independent distribution**: a typed Python wheel with both CLI
  entry points, an ad-hoc-signed native `.app` builder, and a shell-free
  launch-agent renderer using the installed executable's absolute path.
- **Bounded local diagnostics**: the launch agent routes AI-TTS package events
  to one 2 MiB owner-only log plus two backups, suppresses exception payloads,
  and reserves stdout/stderr for no persistent output.

### Changed

- Unified the former Now Playing, Up Next, and synthesis Queue surfaces. The
  current clip is always pinned above two tabs: Queue shows every upcoming clip
  exactly once, and History is newest-first. Internal synthesis and playback
  queues remain separate daemon machinery rather than separate user concepts.
- History re-queue now defaults to Normal (append) and offers an explicit
  Urgent choice (play next after current). The historical row retains its
  original priority as provenance.
- Editorial pass over all documentation: restructured overused em-dash
  connectors into plain sentences and removed small repetitions. No claims,
  decisions, or open questions changed.

### Fixed

- The engine no longer reaches the network to load a model it already has.
  Left to its defaults the upstream package resolved its config, its weights,
  and *each voice pack* through the model host on every load — 49 such
  requests were observed in one session's log, each naming the exact voice.
  For a daemon whose text is client-confidential that is metadata about
  confidential speech leaving the machine, and it made the daemon useless
  offline. Assets now resolve from the local cache first, are remembered for
  the process, and only a genuinely absent file is fetched. Verified at zero
  requests across three voices in two languages.
- Playback now follows the system default output device. The audio library
  resolves its device list once, when it initializes, so a long-lived daemon
  kept speaking to the speakers that existed at startup — connect a display
  with its own speakers and every other sound moved over while speech stayed
  on the laptop. The default output is now read live from CoreAudio, the
  cached enumeration is rebuilt before each clip, and a device change mid-clip
  reopens the stream on the new device from the frame already reached, so
  nothing is repeated or dropped. A device moved while playback is paused is
  adopted before it resumes.
- Hardened GitHub Actions to an explicit read-only token, immutable action
  commit pins, non-persisted checkout credentials, a reviewed `uv` version,
  and frozen project commands that cannot silently rewrite dependency state.
- Enforced the owner-only storage contract for confidential speech. Daemon
  startup now migrates state/cache directories to `0700` and SQLite/audio files
  to `0600`, refuses symlinked state roots, and creates synthesis candidates
  privately before an engine can write speech into them.
- Fixed voice previews and other ready clips appearing under Up Next while the
  Queue looked empty. `Ready`, `Synthesizing…`, and `Queued` clips now share one
  list in actual playback order.
- Made Pause a persistent global playback hold that is available while idle or
  with an empty Queue. Incoming speech continues to queue and synthesize, while
  Skip, Restart, and daemon restarts cannot release the hold; only Resume can.
- Separated daemon admission (`state: accepting`) from `playback_state`, and
  made status/submission responses explicitly tell machine speakers to keep
  submitting while paused because their speech will be spooled.
- Supervised the critical playback worker so an unexpected failure is logged
  and restarted instead of leaving synthesized `Ready` clips stranded after
  Resume releases a global hold.
- Made playback-device failures terminal and visible for the affected clip,
  then continued through Queue. A natural end racing with Pause is recorded as
  `Played` instead of leaving an orphaned paused item.
- Enforced the documented audio-cache cap (configurable through
  `cache_max_bytes`, 1 GiB by default) with persistent LRU ordering. Only
  terminal or orphaned audio is evicted; queued, Ready, Playing, and Paused
  work is protected, and history remains available with `audio_cached: false`.
- Bounded daemon shutdown even when a native engine warmup or synthesis call
  ignores cancellation. SIGTERM now closes the socket and durable store first,
  then exits through a process-lifecycle adapter instead of waiting indefinitely
  for Python's executor finalizers.
- Prevented duplicate menu-bar icons with an OS-backed per-user instance lock.
  The invariant also applies to development launches, where bundle metadata
  and Launch Services cannot prevent a second `swift run` process.
- Removed the launch-agent plist that hard-coded one checkout's virtual
  environment. Release artifacts now install and launch without retaining a
  path to the repository.
- Made daemon JSONL parsing strict and total for bounded input. Invalid UTF-8
  now receives a typed error without poisoning the connection, and the
  configured 1 MiB request limit is no longer shadowed by asyncio's 64 KiB
  default.
- Made failed SQLite commits roll back before control returns. The live daemon
  can no longer observe non-durable queue state that disappears on restart,
  and the database connection factory is an explicit fault-injection port.
- Prevented missing or partial synthesis output from becoming playable. Only a
  non-empty audio artifact can enter `Ready`; engine and best-effort cleanup
  failures remain attached to their item without stopping the worker pool.
- Made audio publication atomic for process crashes. Engines write to
  cache-invisible candidates, startup removes abandoned candidates, and only a
  successful same-directory rename exposes the canonical WAV to playback or
  cache accounting. Rename failures remain isolated to their item.
