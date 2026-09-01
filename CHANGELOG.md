# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-01

### Added

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
- **Menu-bar app** (Swift/SwiftUI, `clients/menubar`): tray icon reflecting
  daemon state, popover with Now Playing / Up Next / Queue / History /
  Settings, transport controls.
- **Infrastructure**: pytest suite written before the implementation, ruff
  `--select ALL` and `mypy --strict` clean, git hooks in `scripts/hooks/`,
  GitHub Actions CI (Python + Swift), launchd agent plist.

## [Unreleased]

### Added

- Daemon: `snapshot` op (status, both queues, merged plan order, history,
  voices, settings in one request); live `position_ms` on the current
  utterance in `status`; `finished_at` on history items.
- Menu-bar app: custom template tray icon family drawn in code (outlined
  idle; dots/bars animate only while synthesizing/playing); event-driven
  refresh over a subscribe stream with reconnect; live progress with
  elapsed/total clocks; Up Next shows waiting-for-synthesis items in true
  plan order with hover actions (move to top, remove); History grouped by
  day with fixed time column, expand-in-place, error text and skipped-at
  detail; per-voice preview buttons in Settings; icon+label tab bar.

### Changed

- Editorial pass over all documentation: restructured overused em-dash
  connectors into plain sentences and removed small repetitions. No claims,
  decisions, or open questions changed.

### Added

- Design documents under `docs/design/`: feature breakdown, architecture, engine
  evaluation, tech stack, UI design with SVG mockups, and an index collecting the
  open questions. No implementation exists; the design is under review.
- Repository scaffolding: README, Apache 2.0 LICENSE, NOTICE, CONTRIBUTING,
  SECURITY, `.gitignore`.
