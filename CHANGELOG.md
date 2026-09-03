# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-02

### Added

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
  clear/status/voices/settings/daemon. Exit 0 means accepted onto the queue;
  `say --wait` and `wait` exit 0 only for Played.
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
- **Infrastructure**: pytest suite written before the implementation, ruff
  `--select ALL` and `mypy --strict` clean, git hooks in `scripts/hooks/`,
  GitHub Actions CI (Python + Swift), launchd agent plist.

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
