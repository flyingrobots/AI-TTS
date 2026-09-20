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

### Changed

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
