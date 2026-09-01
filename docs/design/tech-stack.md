# AI-TTS — Tech stack

Status: **draft for review**. These are proposals with reasoning attached, not decisions. Where a choice could reasonably go the other way, the alternative is written down with the reason it lost, so review can overturn the choice rather than re-derive it.

The constraints doing the work here come from the other documents:

- The engine is **Kokoro-82M, local only** ([engine-evaluation](engine-evaluation.md)). Its reference implementation and its G2P pipeline are Python. Everything about the daemon follows from where the model runs comfortably.
- The daemon is **long-lived and owns the audio device** ([architecture §4](architecture.md#4-components)). Clients are thin and talk NDJSON over a Unix socket, so client language and daemon language are independent choices — the socket is the contract.
- The UI is a **macOS menu-bar popover** drawn to native metrics ([ui-design](ui-design.md)). The mockups specify pt-accurate system typography, vibrancy-adjacent panels and a status item — things web-wrapper frameworks approximate and AppKit does.
- The repo is **Apache 2.0 and public**, so every dependency's licence is a gate, not a footnote.

## The shape: two programs, two languages

One Python daemon, one Swift menu-bar app. A deliberate polyglot cost, paid because each side has a hard constraint the other language fails.

Kokoro's ecosystem is Python. The `kokoro` package (Apache 2.0, from the model's own author) with the `misaki` G2P is the reference path; the MLX and CoreML ports are community-maintained, and at least one has an open report of NaN/silent output — the exact failure class this project exists to eliminate ([engine-evaluation §5](engine-evaluation.md#5-what-would-change-this-answer)). Running the reference implementation in its native runtime is the conservative choice, and the engine adapter ([architecture §8](architecture.md#8-the-engine-interface)) means a faster port can be adopted later without touching anything above it.

A native menu-bar app is the other hard constraint. The UI document commits to real popover proportions, system type at 11–13.5 pt, and an icon that reflects daemon state at a glance. That is an `NSStatusItem` and an `NSPopover`, and pretending otherwise costs either fidelity or a bundled browser.

The seam between them is already load-bearing in the architecture: **nothing the tray can do is unavailable to an agent**, because both speak the same protocol to the same socket. Two languages on opposite sides of a socket is a much smaller tax than two languages sharing a process.

## Daemon: Python 3.12+

| Concern | Choice | Why |
|---|---|---|
| Runtime | CPython 3.12+ | Kokoro's home. The GIL is not a problem here — synthesis time is spent inside PyTorch native code, which releases it |
| Model runtime | PyTorch on MPS, via the `kokoro` package | Reference implementation, Apache 2.0. MLX/CoreML stay behind the engine adapter as future optimizations, not v1 dependencies |
| Audio output | `sounddevice` (PortAudio, MIT) | The playback controller needs a device it can open, pause, and position — not a fire-and-forget `afplay` subprocess it cannot control mid-utterance |
| IPC | `asyncio` Unix-socket server, stdlib | NDJSON framing needs `readline()` and a JSON parser. A framework would be scaffolding around two stdlib calls |
| State | `sqlite3`, stdlib, WAL mode | [architecture §6](architecture.md#6-persistence) chose SQLite; the stdlib driver is enough for a single-process daemon |
| Concurrency | One asyncio loop; synthesis in a thread-pool executor | Playback and IPC are I/O-bound and belong on the loop. Synthesis is the only CPU-heavy work and the executor gives it N workers — N is the setting the architecture asks for |
| Process supervision | `launchd` user agent | The daemon must outlive clients (F3) and restart on crash. macOS already ships the supervisor; adding another is a dependency for a solved problem |
| Packaging | `uv`, `pyproject.toml`, pinned lock | Single-user developer tool installed on its owner's machine, not a notarized `.pkg`. If distribution ever matters this reopens |
| Lint / types / tests | `ruff` (all rules on), `mypy --strict`, `pytest` | House rule: maximal strictness, warnings promoted to errors |

The one genuinely uncomfortable dependency is transitive, and it is worse than the Piper situation flagged in [engine-evaluation §2](engine-evaluation.md#2-local-models): `misaki`'s G2P fallback arrives via `espeakng-loader`, which **bundles `libespeak-ng.dylib` (GPL-3.0) and loads it into the Python process** — dynamic linking, not mere aggregation. Verified against the working install at `~/git/kokoro` (2026-09-01): the venv there holds `kokoro 0.9.4` and `misaki 0.9.4`, both Apache-2.0 by their own metadata, alongside `espeakng-loader 0.2.4` shipping the dylib inside the wheel. `torch` is 2.10.0 — so that machine is already running the exact reference path this document proposes.

What keeps this survivable: GPL obligations attach on *distribution*, and this project distributes source that depends on `kokoro`, never a bundled environment containing the dylib. The hard rule that follows — **AI-TTS must never vendor, bundle, or redistribute its Python environment** — is recorded here so the packaging row above ("uv, not a notarized `.pkg`") reads as the licence boundary it is, not merely a convenience. Worth confirming during review whether the espeak fallback can be disabled outright, because the identifiers this tool speaks are heading for the pronunciation lexicon anyway ([architecture §8](architecture.md#8-the-engine-interface)).

## Menu-bar app: Swift 5.10+, SwiftUI in an AppKit shell

`NSStatusItem` + `NSPopover` as the shell, SwiftUI for the views inside it. The popover content in the mockups — lists, segmented modes, transport controls — is exactly what SwiftUI does cheaply, and the parts SwiftUI still fumbles on macOS (status items, popover behaviors, launch-at-login) stay in AppKit where they are one class each.

The app holds a single persistent socket connection: it subscribes to state events for live updates ([features 6.9](features.md#6-menu-bar-ui)) and issues the same ops any CLI client would. No daemon logic leaks into it. If the daemon is not running, the app says so and offers to start it — that is the whole extent of its privileged knowledge.

Tooling: Swift Package Manager, no Xcode project file if avoidable; `swiftlint` and `swift-format` at maximal strictness; XCTest.

## CLI client: part of the daemon's Python package

`ai-tts say "text" --sensitivity public`, `ai-tts wait <id>`, `ai-tts pause` — a thin argparse wrapper over the socket, shipped in the same package as the daemon so one install produces both. It exits 0 only when the daemon acknowledged the operation, and `wait` exists for callers that need "was actually spoken" ([features 8.5](features.md#8-agent-facing-client-interface)). Agents that want more than the CLI offers speak NDJSON to the socket directly; the protocol is the interface, the CLI is a convenience.

## Rejected options

| Option | What it offered | Why it lost |
|---|---|---|
| **Electron / web tray app** | One language everywhere, familiar UI stack | ~200 MB and a Chromium process for a 360×480 popover. The mockups specify native metrics that a webview only imitates. Wrong tool by an order of magnitude |
| **Tauri** | Native-ish footprint, web UI | Still a webview for the popover, plus a Rust toolchain — a third language whose only job would be hosting the other two |
| **All-Swift** (daemon too, Kokoro via CoreML) | One language, best packaging story | Bets v1 on a community CoreML port with a reported silent-output failure mode. Silence at apparent success is the founding failure of this project; not the place to accept it back as a dependency |
| **All-Python** (tray via `rumps`/PyObjC) | One language, no Swift | `rumps` does menus, not the popover UI the mockups specify. Full PyObjC AppKit is writing AppKit with worse tooling and no Interface Builder escape hatch |
| **Node/TypeScript daemon** (`kokoro-js` on ONNX Runtime) | One repo-wide JS toolchain | Community ONNX port rather than the reference implementation, and a second runtime to supervise. Nothing else in the design wants Node |
| **Rust daemon, Python engine subprocess** | Robust daemon core | The daemon *is* the model host — that is what keeps generation warm. Splitting them reintroduces a process boundary inside the hot path and doubles the supervision problem for a robustness the asyncio daemon does not demonstrably lack |
| **gRPC / protobuf IPC** | Typed schema, codegen | [Architecture §5](architecture.md#5-ipc) chose NDJSON over UDS deliberately: inspectable with `nc`, no codegen step for agent authors, and the message set is small. A schema can be reintroduced as JSON Schema validation without changing the wire |

## What would change these answers

- **The espeak-ng fallback cannot be cleanly disabled or isolated.** Then the G2P path needs re-examination before anything ships, because a GPL runtime dependency in an Apache repo is exactly the contamination the licence gate exists to catch.
- **PyTorch-on-MPS synthesis proves materially slower than the reported figures.** The engine-evaluation numbers are secondary-source and unverified. If real-world synthesis cannot stay ahead of playback, the MLX port gets promoted from optimization to requirement, and its silent-output report gets investigated rather than avoided.
- **Distribution beyond this one machine.** Signed, notarized bundles change the packaging answer entirely and strengthen the all-Swift case.
- **SwiftUI's status-item support matures** to where the AppKit shell is dead weight. Cheap to adopt; nothing depends on the shell's internals.

## What I could not establish

- **Actual synthesis throughput of `kokoro` on PyTorch/MPS on the target machine.** Every performance figure inherited from the engine evaluation is `unverified`. Fix: a ten-line spike script against the environment that already exists at `~/git/kokoro`, timed, before the queue design is validated against real numbers.
- **Whether `sounddevice` supports pause-and-resume at a sample offset cleanly on CoreAudio**, which within-utterance rewind ([architecture §10.1](architecture.md#10-open-questions-for-review)) would need. If it does not, the fallback is chunk-granular seeking, which is another argument for utterance-level rewind in v1.
- **Whether `misaki` operates fully without espeak-ng present.** The working install at `~/git/kokoro` has `espeakng-loader` present, so it demonstrates the path *with* the fallback, not without it. This is the licence question above wearing its practical clothes.
