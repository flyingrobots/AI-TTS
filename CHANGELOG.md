# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- MCP `requeue_speech` works again (issue #211). The daemon's requeue reply carries `composite` and `segment_count`, which `RequeueSpeechReceipt` refused as extra fields, so every call failed with `invalid_response`. The receipt now carries both, with the same defaults as `EnqueueSpeechReceipt`. The Rust `ai-tts mcp` follows from the re-recorded Python 3.12 tool catalog and sessions.
- CI now fails when `Cargo.lock` pins a Rust crate with a RustSec advisory (issue #198). The supply-chain job runs a pinned cargo-deny 0.21.0 advisories check offline against a fetched database whose commit it records in the retained evidence. Previously only the Python lock was audited, so `zip` 2.6.1 reached main with critical advisories.
- The Rust `aitts-daemon` joins a connection to its subscribers before writing the `subscribe` acknowledgement, under the same writer lock, so an event broadcast after a client reads its acknowledgement is never lost (regression from #143 / PR #184). Linux CI hung in `a_slow_subscriber_does_not_block_other_subscribers` when the first events were dropped.

### Changed

- `make install` installs the Rust MCP server as `ai-tts-mcp` (issue #139), at the path agents already have registered, so existing host configurations start the Rust server with no change. Roll back with `make install AITTS_MCP=python` (only the MCP server) or `AITTS_CLI=python` (both). `make uninstall` also removes the Rust `ai-tts-mcp`.
- `make install` installs the Rust `ai-tts` client in place of the Python CLI (issue #138). The Python CLI is installed as `ai-tts-py`; the launch agent now runs `ai-tts-py daemon`, and the Rust `ai-tts` hands `daemon` and `tui` to it. Installing needs a Rust toolchain; the build runs before anything is replaced. Roll back with `make install AITTS_CLI=python`. `make uninstall` also removes the Rust `ai-tts`.
- Model workers send streamed audio as length-prefixed binary frames on a second pipe instead of base64 in JSON lines (issue #126). The worker protocol is now version 2: the worker names its version in its first message, and the daemon refuses another version with `WorkerProtocolError`. A worker copied by an older AI-TTS must be refreshed in model setup (**Retry setup**, then **Refresh worker**); the model weights and environment are kept.
- Every local model, including the default Kokoro, now runs only in its own worker process (issue #116). The daemon process imports no model package, and `make install` no longer installs Kokoro or its English model into the daemon's tool environment; it prints `ai-tts model-setup kokoro` as the next step. Until Kokoro is installed, it stays listed and a request for it refuses with that command. Models installed into the daemon's own environment and `AI_TTS_CHATTERBOX_MODEL_DIR` are no longer used, and an importable package no longer marks a model installed. The worker sends frames on a private duplicate of its output descriptor, so a model library that writes to descriptor 1 cannot corrupt them.

### Added

- `aitts-daemon` gains the synthesis scheduler (issue #145, part 4): `synthesis::synthesize` streams a clip from its registered engine into a spool and reports it to the conductor. Audio for a clip cancelled during synthesis is discarded and its file removed. A worker failure mid-stream marks the clip failed and leaves a spool that returns only the written frames and the error. A failed worker restarts before the next clip (`Engine::recover`). If the ledger does not record a report, the audio is kept for `retry`. If the conductor stops first, unreported audio is removed. `aitts-artifacts`: `Spool::create` refuses zero capacity without creating a file, and a reader drains the frames written before a producer error.
- `ai-tts mcp` answers `tools/call` for the 6 MCP tools with arguments as well (part of #139): `enqueue_speech`, `requeue_speech`, `list_speech_history`, `set_captions_enabled`, `assign_speech_voice` and `cancel_queued_speech`. It checks the arguments as the Python server does and sends nothing to the daemon for a refused call. The installed `ai-tts-mcp` is still the Python server.
- `ai-tts mcp` answers `tools/call` for the 15 MCP tools without arguments (part of #139), with the Python server's results and error texts, checked against calls recorded from it (`tests/fixtures/mcp_tool_calls.json`). The tools with arguments follow; the installed `ai-tts-mcp` is still the Python server.
- `aitts-daemon` gains the conductor's bounded channel (issue #145, part 3): `conductor::mailbox` sends every change to the one conductor owner in arrival order. A full channel refuses `try_request` and makes `request` wait; requests after shutdown are refused and change nothing.
- The Rust `ai-tts` has an `mcp` subcommand (part of #139), also started by the name `ai-tts-mcp`: the MCP stdio server with the same `initialize` reply, protocol version negotiation, and 21-tool `tools/list` as the Python server, checked against sessions recorded from it (`tests/fixtures/mcp_session.json`). Tool calls are not ported yet; the installed `ai-tts-mcp` is still the Python server.
- `aitts-daemon` persists conductor changes (issue #145, part 2): `conductor::durable::Durable` records every state and order change through `aitts-store` before it takes effect, so a crash leaves storage equal to the state before the failed call. A restart restores the queue with playback held. `Command::Requeue` replays a history item. `aitts-store` gains `Queue::reorder`.
- The Rust `ai-tts` client (`aitts-cli`, part of #138) now has `wait` and `say --wait`. They use the daemon event subscription, exit 0 only for `Played`, 3 for another terminal state, and 2 after `--timeout`. The Python `ai-tts` is still the installed command.
- `aitts-daemon` gains the conductor's queue state core (issue #145, part 1): `conductor::Conductor` owns the queue, the playback hold and the preemption stack, and changes them only through commands (submit, cancel, clear, reorder, pause, resume, audio ready, synthesis failed, playback finished) and two planning calls. It follows the Python ordering, clear and nested preemption rules. It does no I/O and is not yet connected to the socket.
- `aitts-artifacts` completes issue #136 with the cache (part 5): `GeneratedStorage::inventory` and `remove` read and prune a Python-written cache to the same rows, counts, and remaining files. The spool now writes through a `SpoolStorage` seam; on a full disk an append fails with `StorageFull`, the reader receives no unwritten samples, and the sealed header claims only the stored samples.
- `aitts-artifacts` gains the last two clip-evidence writers (issue #136, part 4b): `submitted` (`source.txt`, `request.json`) and `audio_generated` (`audio.json`). Their records equal the Python records parsed, for 16- and 24-bit PCM, 32-bit float with NaN and infinity, and an extensible (WAVEX) file. Other sample formats, including 32-bit integer PCM, are refused, and no record is written. The spool now reads WAV headers through the same parser.
- `aitts-artifacts` gains the clip-evidence writers (issue #136, part 4): `prepare`, `record` and `generated`. They leave the same files and parsed records as the Python `ClipEvidence` writers, in owner-only directories, and rotate a log at the same event, because lines use Python's `json.dumps` spacing. Unlike Python, the caller supplies the clock and process session, and write errors are returned instead of logged.
- `aitts-artifacts` gains the clip-evidence ZIP export (issue #136, part 3). It writes the same entries, in the same order and with the same bytes, as the Python `ClipEvidence.export`, and an equal `manifest.json`. The destination must be a new absolute `.zip`; the archive is owner-only; symbolic links are not exported; audio outside the cache root is refused with no partial archive left. Unlike Python, the caller supplies the export time and `export_runtime`.
- `aitts-artifacts` gains the audio spool (issue #136, part 2): the Rust form of `SpoolingPCMStream`. It writes PCM to an owner-only WAV, feeds a bounded ring, re-reads overflow and seeks from the file, and seals a header byte-identical to Python's `wave` output. It streams a Python-written cached WAV unchanged and reports a truncated one as an error.
- A Rust `aitts-artifacts` crate starts issue #136 with owner-only file controls and atomic audio publication, in the Python daemon's layout. Directories are created 0700 and files 0600 through `O_NOFOLLOW` descriptors; a symbolic link or FIFO in place of a private file is refused. A WAV is written to a hidden `.<id>.wav.part` candidate and renamed onto `<id>.wav`, so a reader never sees a partial file, and crash candidates are deleted at start. The spool, clip evidence, and cache follow in later changes.
- A Rust `aitts-cli` crate builds an `ai-tts` binary that needs no Python (part of #138). For every command except `wait`, `say --wait`, `daemon`, `tui` and `mcp`, it accepts the same arguments as the Python CLI, sends the same request, prints the daemon reply as JSON, and exits with the same status (0 accepted, 1 daemon error or refused command line, 2 unreachable daemon or argument error). A shared table, `tests/fixtures/cli_parity.json`, is checked against both CLIs. The Python `ai-tts` is still the installed command.
- A Rust `aitts-client` crate (#131) sends one request and reads its reply with a time limit, and reads a daemon event stream that subscribes again after the daemon restarts. A daemon that is not running gives a typed `Unreachable` error with exit status 2, as in the Python CLI; a reply that is not valid JSON is an error, never a success.
- A Rust `aitts-engine` crate (#133) holds the engine interface, an engine registry, a supervisor for the Python model workers over protocol version 2, a loopback-only HTTP engine, the worker model catalog with the shared pinned digests, and the setup digest check. The supervisor stops a silent or failed worker together with its process group, and a failed worker stays failed until it is restarted. The Python daemon is unchanged.
- A Rust `aitts-daemon` crate builds an `ai-ttsd` binary with process start and stop, the Unix socket server, and the operations that only read state: `status`, `get`, `list`, `history`, `voices`, `settings` without `set`, `metrics`, and `snapshot` (issue #143). It takes the same `<socket>.lock` lease as the Python daemon, so a second daemon of either kind refuses to start; it replaces a socket file that no process serves, binds the socket with mode 0600, and stops within 3 seconds of SIGTERM, SIGINT, or SIGHUP. It refuses every operation that changes state with `bad_request`, plays no audio, and runs no engine. It is not installed or started by `make install`. `aitts-store` gains `Store::counts`.
- A Rust `aitts-store` crate opens the same SQLite state file and schema as the Python daemon, behind four interfaces: queue, history, settings, and voices (issue #135). It never changes the schema version. Checked-in databases written by Python, including an old one without the `engine` column, the recovery crash matrix, and unfinished streaming jobs, read and recover to the same rows in Rust; Python reads a Rust-written database the same as its own.
- A pure Rust domain crate, `aitts-domain` (#130), carries the daemon's text segmentation, spoken-Markdown projection and voice-source classification with explicit parser and allocation budgets, matched against the Python behaviour by a shared corpus. It vendors a pinned, hash-verified Markdown parser under `vendor/markdown`.
- A Rust protocol crate, `aitts-protocol` (#125), defines the shared wire types for requests, replies and events, exports their JSON schema, and decodes one bounded JSON line at a time. Decoding is shape-strict: records accept only JSON objects and closed vocabularies only JSON strings, so an array in field order or a single-entry map form is refused.
- A worker adapter that no longer matches its installed runtime is reported as stale, and `model-setup` refreshes it only on an explicit code-only request (#164). If cleanup after a setup or refresh fails, synthesis resumes, the original failure is kept, and an unclosed worker blocks new setup until AI-TTS restarts.
- Raw `submit` accepts `playback: false` for synthesis-only clients. Per-segment WAV readiness and local paths are available through `get`; these utterances never enter host playback. Daemon `status` reports version 0.2.0 so clients can check support before submitting.
- Add Antigravity (`--agy`) MCP and skill installation. Always attempt skill installation after an MCP failure. Repeated Claude registration accepts only a successful query confirming the same complete one-line command; query failures and mismatched registrations remain failures.
- Guided local model setup: Settings and the `ai-tts model-setup` / `ai-tts cancel-model-setup` commands discover, download, cancel and retry Kokoro, Kokoro · Apple Silicon (MLX) and Chatterbox Turbo. Each model gets its own private Python 3.12 runtime with hash-pinned dependencies and a pinned model snapshot, served by an isolated worker process. The `engines` response and snapshot gain a `models` list. **Use model** selects a model explicitly; setup never selects one. The daemon's own Kokoro adapter shows as installed whenever its package is importable, even before it first warms up.
- Kokoro and Kokoro MLX speech starts playing from the first generated PCM while synthesis continues. A prepared callback device plays from a bounded memory ring, and a separate feeder spools the complete WAV for replay. Pause, rewind, and preemption keep their source offsets. Readiness and cache publication commit atomically, and restart recovery requeues unfinished generation with playback held. Other engines keep file playback.
- Streamed speech starts and stops as softly as file playback. A stop, pause, or route move fades the next 20 ms of source without moving the playhead (the fade is capped at one callback block, which is longer than 20 ms with the host block below). Near the end of a clip the fade holds the last sample. A session that closes its own stream then writes 100 ms of silence. A stream opened mid-clip, on resume, a route move, or a preemption restore, fades in over 20 ms from exact zero, and a close during that fade-in starts from the gain it had reached.
- Streamed chunks keep truthful records through failure and restart. If generation fails after a streamed document chunk is already Ready or Playing, that chunk is marked Failed with the engine's error, instead of Cancelled with no error. Restart recovery leaves a streamed chunk skipped if the listener skipped it before the daemon stopped. Daemon shutdown holds playback only if it is not already held, so a microphone hold keeps its on-screen reason after a restart.
- The streaming callback output requests the same device-rate host block as file playback: a 21.3 ms I/O buffer instead of 5 ms, so app switches do not pop during streamed speech either. Measured on the built-in speakers, this raises the stream's reported output latency by about 33 ms (44.8 to 77.4 ms). The 194–205 ms first-audio figure in the README was measured with the old 240-frame block, before this change, and has not been re-measured.
- The default speech engine switches live, without restarting the daemon, through `ai-tts settings set engine NAME`, `settings --engine NAME`, `settings --set engine=NAME`, or the composer's model picker. Each accepted clip records its engine in a new `utterances.engine` column, and its segments, replays, and restart-recovered work keep it; rows from older databases bind once to the startup engine. A new `engines` IPC op and `ai-tts engines` list each registered engine's voices, locality, and readiness, and `ai-tts say --engine NAME` overrides the default for one clip. Private text is checked against the chosen engine at admission and again before synthesis. While the startup engine prepares, only clips recorded for it wait. A saved voice the new engine lacks is reported as that engine's default and kept for a later switch back. A saved default whose adapter is not configured at launch starts the daemon on Kokoro. The `restart_model` IPC op takes an optional `engine` name, so a failed engine that is not the default can be reloaded.
- An `openai-audio` adapter speaks through a separately managed OpenAI-compatible server on loopback only (`AI_TTS_OPENAI_URL`, `AI_TTS_OPENAI_MODEL`, `AI_TTS_OPENAI_VOICE`). It pins `localhost` to 127.0.0.1, ignores proxies, follows no redirects, bounds responses to 64 MiB with a 30-second socket timeout, and publishes only a complete WAV with finite samples. Its readiness is reported as server managed.
- A `chatterbox` extra adds native Chatterbox Turbo from an explicit local snapshot (`AI_TTS_CHATTERBOX_MODEL_DIR`), with its one `default` voice, its upstream watermark kept, and generation speed fixed at 1. A clip that names no speed uses 1 and keeps the saved speed for other engines; an explicit other speed is refused. The extra installs two pinned upstream source archives, and CI audits them separately from the hashed PyPI graph.

- Measured architecture review with Mermaid diagrams, reproducible controller/PCM/MLX benchmarks, retained baseline evidence, and scheduled CI guards for gross performance regressions.

- Paragraph-level chunk navigation for ordinary responses of at least 60 words. Substantial paragraphs become separate clips, small blocks stay attached to neighbors, and short single clips retain their identity.

- Long documents (over 180 words) now break at every paragraph group of at least 20 words too, instead of packing paragraphs toward the 180-word target. Five 50-word paragraphs give five chunks where they used to give two.

- `ai-tts tui` provides an optional Textual dashboard with live progress and measured output level, chunk controls, Vim-style queue editing, and one-key history replay. It reconnects to the daemon and can close without stopping speech.

- Subscribers now receive `state_changed` with `from: null` and `to: "Queued"` when a submission or history replay is admitted. Work queued behind busy workers now appears right away.

- Optional pre-speech chime, once per document, and opt-in other-app ducking while the menu-bar app is running. Both are off by default; opt in under Settings or with the CLI, which save both preferences. Ducking stays off by default until the tap's hardware buffer is validated ([#70](https://github.com/flyingrobots/AI-TTS/issues/70)), because a missed tap cycle would glitch every other app's audio. macOS system-audio routing lowers other apps to 30%, restores them when speech pauses or ends, and keeps AI-TTS volume unchanged. A chime cut short by pause or skip fades out over 20 ms, on file and live-stream playback alike, before the stream closes.

- Speak… replaces the menu’s immediate Read actions with an editable composer, voice and active-model choice, text/Markdown interpretation, and text/Markdown/PDF attachment. Clipboard and selection imports append to the draft; submission errors preserve it.

- Drag the menu card’s bottom grip to resize its height. The height persists across launches and is bounded to the current screen.

- Optional `kokoro-mlx` backend on Apple Silicon/Python 3.12, selected through a persisted engine preference or daemon flag. Preparation precedes queued synthesis; unsupported installations fall back to reference Kokoro. Clip evidence fingerprints MLX assets and runtime versions.

- `say --preempt`, `priority: preempt`, and MCP `preempt: true` interrupt playback when alert audio is ready, then resume the interrupted chunk and offset. Nested alerts unwind in reverse order; holds remain authoritative, queue clearing drains suspended clips, and device stops fade to silence.

- Manage Files lists generated storage and deletes individual or all eligible clips with their source and evidence. Opt-in 1/7/30/90-day retention defaults to Never. Clear History can also remove generated files while protecting active and queued work.

- The menu shows model readiness and daemon PID/uptime, offers safe model reload and daemon restart, and provides Launch daemon, View Logs, and Quit when disconnected.

- The menu footer’s voice selector changes the default for new submissions and confirms the change. Existing queued voices and explicit caller assignments retain their values.

- History reports export per-clip audio, source, BLAKE3 identities, generation/model provenance, and synthesis/playback logs including pause causes. Open Data Folder reveals the local files; reports stay local and identify missing legacy evidence.

- Captions can be placed at the top or bottom of the screen; the preference persists and takes effect immediately.

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
  `previous_segment` ops and as buttons beside Skip that remain visible and disabled when the
  current clip has no additional chunks. Forwards gives up one chunk; backwards replays the
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
- **The daemon can now measure the claim it is built around.** A `metrics`
  op, an `ai-tts metrics` command and a `speech_metrics` MCP tool report the
  two waits separately: submitted-to-Ready is what synthesis cost and is
  parallel work, while Ready-to-Playing is what the queue cost and no amount
  of parallelism helps it. Queue depth, cached bytes against the configured
  cap, and playback device failures counted apart from ordinary terminal
  states. A null summary means nothing has been measured, which a caller can
  tell from zero.
- **Pause is reachable from the keyboard**, as `p` while the popover is
  focused. It is the most-pressed control in the app — it is what you reach for
  when speech starts during a call — and it was the one transport control with
  a tooltip and no key. It is now a `TransportAction` like the rest, so its
  label and its key are values a test can check rather than modifiers at a
  call site.
- **GitHub Issues is the only defect tracker.** Known defects and deferred
  work are filed as issues rather than kept as Markdown in the repository. Two
  lists is one list recorded wrong: an in-repo file and an issue for the same
  defect disagree within a release, and the issue is the one people find. The
  issue and pull-request templates and `CONTRIBUTING.md` point there.
- **A walkthrough of one utterance**, at
  [`docs/design/one-utterance.md`](docs/design/one-utterance.md): what actually
  runs, in order, from an agent's `say` to the state change that ends it,
  naming the module and symbol at each step. The architecture document says
  what the parts are and why; this is the one to read before changing code.
- **The README's CLI examples are pinned to the CLI that exists.** A test
  fails when a subcommand has no example, or when an example names a command
  that has been removed. Seven commands had been added without one, so the
  README described a smaller tool than the one installed.
- **The voice catalog can be extended without a release.**
  `AI_TTS_EXTRA_VOICES` adds voices to the curated list — for someone who has
  installed the Japanese or Mandarin G2P extras themselves, or who wants a
  voice a new upstream release added. Declared names are validated for shape
  and de-duplicated: a name the catalog offers but cannot speak would fail at
  synthesis instead of where it was typed. The curated list stays the default
  because every entry in it was verified against the dependencies this project
  installs.
- **A first run no longer looks like a hang.** The engine's weights are
  around 330 MB and arrive on first use; until they did, a clip sat in
  Synthesizing with nothing to distinguish a download from a wedged daemon.
  The snapshot now carries `engine_preparing` — which asset is being fetched
  and since when — and the menu bar shows it. Named rather than measured: the
  model host reports no progress worth trusting, and an invented percentage
  would be worse than an honest "still fetching this".
- **Model asset failures say what to do.** A file that is cached but
  unreadable and one that is absent and unreachable now read differently and
  name the repository, because only one of them is fixed by connecting to a
  network. The transport error stays out of the message, as it can carry a URL
  and proxy details.
- **A quiet model load.** Building the engine's model raised ninety-two
  warnings from inside torch, about torch APIs this project does not call. The
  known ones are now silenced for the duration of the load and by subject
  rather than by category, so a warning that actually concerns this project —
  including a future deprecation of its own — is still heard.
- **One clip is followable through the log.** Lifecycle events now carry a
  short `trace=` token derived from the utterance identifier, so a stuck clip
  can be diagnosed by reading the log instead of reading state out of SQLite.
  It is emitted when a clip becomes playable, takes the device, finishes or
  fails, when synthesis fails, and on the two lines that explain why nothing
  is playing — a terminal document being released and a document that cannot
  resume. Derived rather than stored: no schema change, and the token can
  carry no speech, source label or path.
- **A Makefile as the entry point for a clone.** `make` builds the menu-bar
  app, `make install` installs the executables, the app and the launchd agent,
  and `make install-agents` wires it into every local coding agent found. It
  refuses to run off macOS at parse time rather than half-installing, and
  `make doctor` reports what is up and what is wired in without changing
  anything.
- **`scripts/install-integration.sh`**, which the agent targets delegate to and
  which takes the agents by name: `--claude`, `--codex`, `--gemini`, `--all`,
  plus `--dry-run`. An agent whose CLI is absent is skipped rather than failing
  the run, and a dry run prints each host's own `mcp add` command so an
  unsupported agent can be wired up by hand.
- **A bundled skill** at `skills/speak/SKILL.md`, following the open
  agent-skills layout, so the same file installs for Claude Code, Codex and
  Gemini. The installer substitutes the committed `<AI_TTS_BIN>` placeholder
  for this machine's path, so an installed copy names a real executable while
  the committed one stays machine-independent. It states the same speech policy
  the README describes for any shell-capable agent: check `status` before
  speaking, treat a hold as a reason to write instead, pass a stable
  `--source`, let the daemon decide the voice, and write for the ear rather
  than the terminal.
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

### Security

- `aitts-artifacts` now uses `zip` 9 (resolved 9.6.1) instead of 2.6.1, which fixes GHSA-m665-v7pm-7grj (critical, ZIP cloaking parser differential; fixed in 9.0.5), GHSA-q7v9-x93c-xqv3 (high, unbounded symlink targets; fixed in 9.0.0), and GHSA-8hxf-qr8p-62x4 (medium, AES HMAC bypass on premature EOF; fixed in 9.0.0). The evidence export writes the same archive entries; only the tests' ZIP reader call changed for the new API.
- Guided model setup checks every downloaded model file against a SHA-256 digest pinned in the catalog before any file is loaded, so a substituted or corrupted download (including pickled torch weights) is rejected instead of deserialized.
- Guided setup creates its diagnostic log and runtime manifest exclusively with owner-only permissions and never writes through a symlink planted at either path.

### Changed

- Python test tier budgets now gate on process CPU time, including setup, teardown and waited child processes, instead of summed wall time. Wall totals and call p95 remain informational; per-test wall deadlines and the existing tier limits are unchanged.

- The medium test tier's time budget is re-baselined from 45 to 120 seconds, because the tier's cost of 22–56 seconds made 45 seconds alarm on machine noise. Small and large budgets and per-test ceilings are unchanged. Issue #72 tracks reducing the installation tests' cost.

- Installation now starts the menu-bar app independently at login and recovers abnormal exits. Intentional Quit keeps it closed, and reopening restores crash recovery. Uninstall removes both launch agents.

- A submit response's `eligible_engines` lists registered engine names (for example `["kokoro"]`) instead of the `["local"]` placeholder, and the settings `engine` value reports the engine actually selected in the running daemon rather than the stored preference.

- Speak opens an inline composer beneath playback, preserving drafts when collapsed; CC cycles Off, Bottom, Top.

- History provenance appears in a compact, scrollable hover card instead of expanding the row; clicking remains available for keyboard and accessibility use. The card opens after the pointer rests on the button for 400 ms, so moving the pointer across History opens no cards and sends no daemon requests.

- Simplified the internal speech store by removing an unused queue lookup and
  making its pending-queue helper private. Playback and queue controls are
  unchanged.

- The Python suite's latency budget is now per class rather than one number
  for the whole suite, charged on measured test time including fixtures, and
  each run prints the count, charged total and p95 call latency per class. The
  single 30-second whole-suite gate had started tripping intermittently at 545
  tests, which is the worst state a gate can be in. Two test modules that had
  been marked `small` while starting a daemon or spawning a subprocess are now
  `medium`, which is most of what the small tier was actually costing.
- The menu bar's `Views.swift` split by surface into the popover shell,
  `CurrentPlaybackViews`, `QueueViews`, `HistoryViews`, `SettingsViews` and
  `SharedViews`. It held every popover surface in one 1257-line file; no view
  body changed, and each file now says at the top which surface it is and what
  that surface is for.
- The per-client voice register moved out of the daemon into
  `aitts.voice_registry`, and the listener-interrupt loop into
  `aitts.input_interrupt`. Both are durable policy with their own rules rather
  than steps in handling a request, and the reasons those rules are the way
  they are now sit next to the code that enforces them. daemon.py is down from
  1097 lines to 855; behaviour is unchanged and the whole suite is the
  regression evidence.
- The settings table moved out of the daemon into `aitts.settings`. It was the
  largest thing in there with nothing to do with queues, and its validation
  rules could not be exercised without standing up a daemon, a store, an
  engine and a sink — which is why several of them had no test. The two
  settings that reach live components rather than the table name what they
  need as one seam.
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

- The hard-deadline runner now cleans up remaining members of its process group when the command leader exits on SIGTERM but a descendant ignores it. The existing grace period and timeout exit status are preserved, and the leader remains unreaped until the final signal so a reused group identifier cannot target unrelated processes.

- Architecture §9a distinguishes host audio access, native Swift entrypoints, and the daemon's non-macOS platform fallbacks; it no longer claims CoreAudio is required for daemon execution.

- Git hooks no longer pass repository/index overrides into validation, and pytest clears inherited Git environment variables before each test's function-scoped fixtures. Module imports and higher-scoped fixtures must still isolate their own Git subprocess environments.

- Paired controller benchmarks load playback helpers from each measured checkout, support the pinned historical layout, and fingerprint those helpers separately from the shared harness. Reference cleanliness checks now include test support; shared helpers live in `tests/support/playback.py`.

- Benchmark references reject ignored Python source, sourceless bytecode, native modules, symlinks, and opaque nested repositories under `src`, closing the remaining import-shadowing gap. Ordinary tagged bytecode caches remain allowed; the pinned historical reference is unchanged.

- Uninstall stops before deleting either launch-agent plist or the CLI when launchd refuses to stop the loaded daemon, matching the menu-bar agent safeguard.

- Switching from a prepared streaming model to Chatterbox waits for native audio completion before closing the old device, preventing overlapping shutdown calls. A stalled microphone-device query no longer freezes daemon status/control or prevents process exit. Unconfirmed audio shutdown remains an explicit error and blocks device reuse ([#94](https://github.com/flyingrobots/AI-TTS/issues/94)).

- Streaming playback no longer crackles when live synthesis falls behind, for example when several history items are replayed at once and synthesize at the same time.
  - **Fade:** an underrun now fades the real upcoming audio over the 20 ms raised cosine used everywhere else. Previously it ramped a held sample over 5 ms.
  - **Rebuffer:** playback then stays silent until 300 ms is buffered, instead of restarting on every scrap.
  - **Resume:** it fades back in over 20 ms from the frames it faded out, so nothing is lost.

  A trickling synthesis previously restarted on every callback (30 restarts in 30 callbacks in the regression test). It now produces one clean gap. A fully written stream that is only waiting for publication plays to its end instead of counting as an underrun.

- `make install` now installs the terminal dashboard. The tool install includes the `tui` extra, and Textual is pinned to `uv.lock`, so `ai-tts tui` works straight after installing. The README's previous instruction, `uv tool install --force '.[tui]'`, replaced the whole tool environment without Kokoro, its English model or the lock constraints, which broke speech. The README now warns against it and offers `uv run --extra tui ai-tts tui` for trying it from a checkout.

- Installation waits for a quit menu-bar app to exit before registering its launch agent, so the new instance doesn't lose the single-instance lock and stay closed. It retires the running app with SIGTERM rather than an AppleScript quit, so no Automation permission prompt appears; an app that is still running after ten seconds produces a warning instead of a failed install. The menu-bar app treats SIGTERM as a normal Quit, so ducked media is restored when the installer or `launchctl bootout` stops it.

- `make uninstall` reports failure and keeps the menu-bar plist when launchd cannot stop a loaded menu-bar agent. Reopening the installed app falls back to a standalone launch if `launchctl kickstart` hangs for more than two seconds, and a stalled `ps` or `kill` during installation can no longer hold up the install.

- Skip, stop, pause, resume, and output-device moves no longer pop. When a stream closes mid-clip, the sink fades the audio that would have played next over 20 ms, without moving the playhead, then writes 100 ms of silence before closing. CoreAudio can cut the in-flight hardware buffer when the stream stops, and that cut now lands on silence rather than speech. A stream that opens mid-clip, on resume or after a device move, fades in over 20 ms instead of starting at full amplitude. The fade-out stays smooth near the end of a clip, after an interrupted fade-in, and when a pause is resumed immediately. Previously pause and device moves had no fade, and stop had only a 5 ms ramp.

- Playback no longer pops when another app activates mid-clip. Left to choose, PortAudio asked CoreAudio for 15-frame (0.3 ms) I/O cycles, so a 13 ms page fault on the audio thread skipped a cycle. The output stream now requests a host block sized from the output device's sample rate for a 21.3 ms I/O buffer: 1024 frames at 48 kHz, as measured on the built-in speakers. Other devices get the same duration at their own rate. The cost is about 0.13 s more delay before pause and skip are heard.

- `make install` constrains the uv tool install to the versions in `uv.lock`. `uv tool install` ignores the lockfile, so the release of huggingface-hub 2.0 sent the resolver back to transformers 4.12.2, whose tokenizers 0.10.3 fails to build, and every fresh install failed. The README's manual and MLX install commands use the same constraints.

- `make install` rebuilds the ai-tts package on every run. uv reused its cached build of the checkout whenever the version stayed the same, so an install could report success while the daemon kept running the previous code.

- `make install` waits for launchd to finish tearing down the previous agent before bootstrapping the new one, instead of failing with `Bootstrap failed: 5: Input/output error` after a successful build. If the old service has not left after ten seconds, it gives up with a reason and restores the previous configuration.

- Icon-only history, queue, settings, voice and dismissal controls expose functional accessibility names; the re-queue menu retains its name across UI redraws.

- The native menu-bar control exposes an accessible app name and current status instead of an unnamed image button.

- The menu-bar app renders its initial unavailable-state icon immediately, remaining discoverable when the daemon cannot answer.

- Interrupted launch-agent activation restores the previous plist and registration state, including launchctl side effects completed before Ctrl-C reaches the installer.

- App and launch-agent CLIs report concurrent destination conflicts as concise usage errors while preserving the winning installation.

- Agent integration preserves embedded and trailing newlines in executable paths instead of failing skill rendering or silently changing the path.

- Installation reports launchd registration without claiming the daemon is healthy or running; `make doctor` remains the explicit status check.

- If launchd rejects an updated service configuration, installation restores the prior plist and attempts to reload it only when the service was previously loaded. A loaded service without a recoverable plist is not stopped.

- `make install` prepares the signed app and launch-agent plist before replacing the CLI, so build or preparation failures cannot partially upgrade the executable installation. Explicit app, plist, and log destinations are passed through consistently.

- `make doctor` reports a failed daemon status check when the executable is found through uv rather than PATH.

- Skill upgrades render to a sibling temporary file before replacement, preserving the installed SKILL.md when rendering fails.

- Failed MCP registration no longer removes an existing agent registration or reports success. Other selected agents are still attempted, and the installer exits nonzero if any registration fails.

- Forced app upgrades build, package and sign a sibling candidate before atomically swapping it into place. Build failures preserve the installed app, and unsupported filesystems fail without deleting it.

- Forced launch-agent upgrades preserve the existing plist if validation or serialization fails, and publish only a complete replacement. Unforced installs refuse concurrent replacement.

- Completed audio sinks can be acquired immediately after `wait()` returns, even if the previous Python worker thread is still retiring. Active playback remains protected against overlap.

- Daemon shutdown retires active audio and its completion watcher before closing state or releasing ownership, preserving the final parent/child position for explicit resume.

- Pause arriving during Restart device teardown now keeps playback silent; explicit Resume honors the requested restart from zero.

- Private-file validation refuses unexpected FIFOs without blocking startup or diagnostic-log setup while waiting for a pipe peer.

- IPC rejects isolated Unicode surrogate escapes before dispatch, returning a typed refusal without leaving voice assignments from a failed submission.

- Recovery settles documents whose final child completed before the parent completion commit, preserving played duration and releasing the queue.

- Updated frozen PyJWT to 2.15.1 for the recursive payload error-handling vulnerability CVE-2026-101918.

- Skipping a document now commits the parent, active child, and unfinished siblings together, preventing later chunks from returning after an interrupted Skip.

- Recovery carries a committed child synthesis failure to its still-active parent instead of leaving the document stranded in the queue.

- Recovery repairs a document whose first child audio committed before its parent became Ready, including another crash during that repair.

- Restarting with Ready playback now engages the durable global hold, requiring explicit resume even if the process stopped before any clip began playing.

- Cached replays retain generation-artifact identity after audio eviction, so provenance and reports can still find retained evidence. Existing audio references are migrated on database open; previously lost links cannot be reconstructed.

- The frozen urllib3 dependency is updated to 2.8.0 for proxy-TLS isolation, Deflate streaming, and oversized chunk-header vulnerabilities, with an in-memory chunk-header regression.

- Competing daemon starts now refuse an already-owned state directory or socket instead of recovering a live queue or replacing its endpoint; failed startup releases acquired resources.

- Daemon shutdown now retires active IPC handlers before closing application state and refuses buffered requests after serving stops.

- Cancelling a model-reload request no longer releases synthesis exclusion early or leaves model readiness stuck; the daemon owns reload completion.

- Python application modules no longer select concrete CoreAudio adapters; platform factories live outside the application boundary, with a static-import regression gate.

- Clearing or successfully submitting a composer draft retains its chosen text interpretation, voice, and model.

- Composer selection imports follow the latest external application activation; unavailable targets are cleared instead of reusing an older app.

- Speech-composer provenance now identifies user composition while preserving import attribution and replay origin.

- Automatic screen fitting no longer overwrites the preferred menu height; returning to a larger display restores it.

- Menu heights above 1200 points remain intact across relaunches on tall displays.

- The menu resize grip supports keyboard arrows and accessibility increment/decrement, and exposes its current height and bounds.

- History removal prunes cached provenance, and late requests cannot restore details for removed clips.

- History exposes a clearly labeled Show/Hide provenance button with a full clickable target and selectable clip details.
- Engine switches use and report a compatible default voice while preserving the saved preference for compatible engines.
- MLX startup now falls back to reference Kokoro when required English language assets are missing.

- Refreshing a suspended playback offset preserves the parent transition timestamp and does not emit a duplicate Paused event.

- Preempted document chunks emit their committed segment state-change event; paused-offset refreshes do not duplicate it.

- Playback evidence includes driver underflows reported while writing the stop fade.

- The native Queue shows suspended speech and keeps Clear Queue available during preemption; suspended clips cannot be reordered or individually cancelled.

- Native Queue and History preserve preempt priority and offer it in the requeue menu.

- Nested speech interruptions recover in their queue-defined order even when wall-clock timestamps tie or move backward.

- History replay provenance identifies the replay while retaining its original caller.

- Rejected storage requests preserve the previous automatic-retention policy.

- Markdown speech cleanup preserves numeric multiplication signs and inline-code
  asterisks while removing loose prose emphasis.

- Evidence reports protect their audio and sidecars from deletion and eviction
  until the archive worker finishes, including after a client disconnects.

- Rejected speech submissions preserve the caller’s existing voice assignment.

- Newly failed speech now shows a local toast with View History and dismiss actions, plus a persistent menu error and tray indicator. Startup and polling do not repeat old failure alerts.

- Concurrent document segments no longer overwrite shared phonemizer state and fail with an input/output line-count mismatch. Neural inference remains parallel.

- Pausing closes the audio output stream; resuming reopens it at the saved frame and current device. Driver underruns are recorded without replaying audio.

- App bundle construction discovers Xcode’s actual Swift module directory, and installation includes the English spaCy model in the daemon environment.

- The internal Store API check now discovers only Store methods, includes
  async definitions and callback references, and ignores comments and strings.
  Repository scans are charged to the medium test tier; duplicate assertions
  were consolidated and the guard has controlled falsification cases.

- Update the frozen PyJWT dependency to 2.14.0 to address ten published
  security advisories, including empty HMAC JWK acceptance.

- Microphone pauses now resume by default once no input device is active.
  Explicit manual pauses and saved `manual` policies remain in effect.
- Agents using the speak skill now enqueue requested speech while playback
  is paused. Status guidance explains that speech is saved for later playback,
  and the skill distinguishes queued speech from confirmed playback.

- The sink's failure path is now tested rather than marked unreachable. A
  device that cannot be opened, a device that fails part-way through a clip,
  and cached audio evicted before the sink opened it all end that clip with an
  error and a non-natural finish — which is what stops a clip being marked
  Played with nothing having been heard. The stream factory the device-follow
  tests already inject was enough to drive all three; no new seam was needed.
- **Releases require a newer Xcode than any GitHub runner offers.** The App
  Intents protocol catalog the bundle build needs is absent from every Xcode
  on the runner image, so CI assembles its bundle with
  `--allow-missing-app-intents` and verifies everything else about it. The
  release job deliberately does not pass that flag: an artifact people install
  without the Shortcuts integration it is documented to have is a silent
  product regression, so a failed release is the correct outcome until a
  runner ships a capable toolchain. Releases are built locally today.
- The first CI run failed three ways, all of them latent rather than new, and
  all of them invisible locally because a developer's environment is richer
  than CI's. `huggingface_hub` had no mypy override — it is not a declared
  dependency at all, arriving transitively through the `kokoro` extra — so
  type-checking failed wherever the extras are absent. One test reached asset
  resolution through the same path and needed the extra to pass. And the app
  bundle needs a newer Xcode than a runner selects by default, which the
  workflow now pins. Each is now pinned by a test rather than by memory.
- **The model was speaking in training mode.** A PyTorch module defaults to
  training mode, where dropout randomly zeroes activations. Upstream's pipeline
  calls `.eval()` when it builds its own model, and this adapter builds the
  model itself so voice packs resolve from the local cache instead of through
  the model host on every load — which bypassed the `.eval()` too. Nine dropout
  layers in the pitch and duration predictor were live on every clip, randomly
  perturbing prosody. Fixed, and pinned by a test that inspects the module tree
  rather than trusting the construction. The `@torch.no_grad()` upstream does
  not cover this: gradients and module mode are different things.
- A rejected settings update no longer applies half of itself. Validation now
  completes for every key before anything is written, so a request that names
  two changes and is refused leaves the client showing an error and its state
  unmoved, rather than showing an error while one of the changes silently
  landed. The live effects — the playback rate and a cache eviction — are held
  back on the same basis.
- `speed` is now refused where it is typed rather than accepted and ignored.
  A settings write of `speed: true` was taken as 1.0, because a bool is an int
  in Python, and an out-of-range speed reached the store through the settings
  path while the submit path rejected it. Both paths now share one range and
  one message.
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
