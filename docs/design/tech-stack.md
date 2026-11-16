# AI-TTS — Tech stack

Status: **implemented for v0.1.0 and the native OS integration goalpost**.
Installed Services dispatch and App Intent indexing have direct system
evidence; representative host, live Accessibility, and real Shortcuts
invocation acceptance remain open. Where a choice could reasonably go the
other way, the alternative is written down with the reason it lost, so a later
review can overturn the choice rather than re-derive it.

The constraints doing the work here come from the other documents:

- The engine is **Kokoro-82M, local only** ([engine-evaluation](engine-evaluation.md)). Its reference implementation and its G2P pipeline are Python. Everything about the daemon follows from where the model runs comfortably.
- The daemon is **long-lived and owns the audio device** ([architecture §4](architecture.md#4-components)). Clients are thin and talk NDJSON over a Unix socket, so client language and daemon language are independent choices — the socket is the contract.
- The UI is a **macOS menu-bar popover** drawn to native metrics ([ui-design](ui-design.md)). The mockups specify pt-accurate system typography, vibrancy-adjacent panels and a status item — things web-wrapper frameworks approximate and AppKit does.
- The repo is **Apache 2.0 and public**, so every dependency's licence is a gate, not a footnote.

## The shape: two programs, two languages

One Python daemon, one Swift menu-bar app. A deliberate polyglot cost, paid because each side has a hard constraint the other language fails.

Kokoro's Python package and `misaki` G2P form the reference path. G2P converts
written text to phonemes for the model. The original evaluation cited an MLX
NaN/silent-output report; it does not establish the condition of current ports.
The later [MLX receipt](../testing-evidence/2026-09-30-kokoro-mlx.md) records
successful real output, but no comparative listening test. Keep the reference
path until a replacement meets the [inference decision](#model-inference-scope).

A native menu-bar app is the other hard constraint. The UI document commits to real popover proportions, system type at 11–13.5 pt, and an icon that reflects daemon state at a glance. That is an `NSStatusItem` and an `NSPopover`, and pretending otherwise costs either fidelity or a bundled browser.

The seam between them is already load-bearing in the architecture: **nothing the tray can do is unavailable to an agent**, because both speak the same protocol to the same socket. Two languages on opposite sides of a socket is a much smaller tax than two languages sharing a process.

## Python feature policy during the Rust port

Decision for [#122](https://github.com/flyingrobots/AI-TTS/issues/122): **allow
Python daemon features during the early port; freeze new daemon behavior when
operation-set completion starts, through validated cutover.** This is a
development policy, not a claim that a Rust daemon has replaced Python.
The stack tables below describe the existing Python implementation and its
original tradeoffs; the linked issues describe the planned Rust port.

Before [#148](https://github.com/flyingrobots/AI-TTS/issues/148) starts, a Python
feature may merge with its normal tests and review. Its PR must identify the
changed public behavior, update the applicable reference cases, and name the
Rust task that will implement parity. The feature owner pays this extra
specification and tracking cost. An early Rust component does not need to
implement every new feature in the same PR.

The first implementation draft PR for #148 starts the freeze. Record the exact
Python reference commit and contract/corpus commit in its testing evidence.
Those commits define the operation set and expected behavior; an old operation
count or an unpinned copy of `main` does not. New Python daemon features wait
until [#151](https://github.com/flyingrobots/AI-TTS/issues/151) has met its
cutover and rollback acceptance criteria. During this interval:

- Defect corrections remain allowed. If a correction changes observable
  behavior, update the reference case and commit pin, and rerun the affected
  comparison against both daemons before claiming parity.
- Refactors and port preparation remain allowed when they preserve public
  behavior. A new operation or setting is a feature even if its patch is small.
- Swift application work is outside this freeze, but a new daemon requirement
  follows the daemon rule. A UI change alone does not waive compatibility.
- Do not declare #148 complete or cut over with an unaccounted reference delta.
  Record any new parity work in the issue graph and recalculate the frontier.

This limits the period in which new Python behavior must wait. A freeze from
the beginning of the port would delay useful behavior while many lower-level
tasks are still incomplete. No freeze at all would leave the final comparison
chasing a moving target. The cost of this choice is explicit parity tracking
before the freeze and delayed features during final validation. If the port is
paused or this cost becomes unacceptable, record a revised decision and set a
new reference before resuming validation; do not silently move the target.

The policy is enforced through PR review and recorded evidence. It does not
add a CI rule that can infer whether a change is a feature. The separate choice
about replacing model inference remains outside this decision. See the
[roadmap sequence](../../ROADMAP.md#python-feature-policy-during-the-rust-port).

## Build and install tooling after the Rust port

Decision for [#123](https://github.com/flyingrobots/AI-TTS/issues/123): **use
Rust for the repository-owned build, install, and audit logic after the port.**
Put developer build, release, and audit orchestration in an `xtask` crate.
Put operator installation and agent registration in the Rust CLI, through
`ai-tts install`. These are target interfaces for the implementation work;
the current tooling still uses Python and shell.

Keep the Makefile as a thin command entry point. The agent integration shell
script may remain as a compatibility wrapper that dispatches to the Rust
implementation. Keep parsing, publication, rollback, and failure handling in
Rust rather than duplicating them in wrappers. Git hooks stay plain shell and
are outside this decision. Nested benchmark tooling and model inference are
also outside its scope.

The decisive requirement is in
[#150](https://github.com/flyingrobots/AI-TTS/issues/150): a machine without
Python must be able to install and start the Rust daemon. A compiled CLI can
own that installation path without an interpreter bootstrap. Keeping the
Python installer would fail that requirement even if the daemon itself used
no Python. Building the Swift application still needs Apple's build, metadata,
and signing tools; changing the orchestration language does not replace them.

The current scripts establish the behavior a port must preserve:

| Responsibility | Source and contract to carry forward |
| --- | --- |
| Bundle construction | [`build_app_bundle.py`](../../scripts/build_app_bundle.py) builds Swift, generates and validates App Intents metadata, signs the bundle, and publishes a complete candidate. Keep the missing/invalid-metadata refusal and the actions, background execution, shortcuts, and playback-rate checks in [`test_distribution.py`](../../tests/test_distribution.py). |
| Installation and launch agents | [`install_application.py`](../../scripts/install_application.py) stages candidates and restores the prior agent configuration on activation failure; [`render_launch_agent.py`](../../scripts/render_launch_agent.py) serializes installed paths into plists. Preserve interruption, teardown, rollback, and complete-bundle publication cases in [`test_launch_agent_activation.py`](../../tests/test_launch_agent_activation.py) and [`test_installation_upgrades.py`](../../tests/test_installation_upgrades.py). These cases do not establish an atomic transaction across the entire current installation. |
| Agent integration | [`install-integration.sh`](../../scripts/install-integration.sh) selects agent hosts, resolves executables, renders skills, and registers MCP commands. Preserve dry-run behavior, path quoting, incumbent preservation, and per-agent error reporting from [`test_install_integration.py`](../../tests/test_install_integration.py). |
| Release and audit evidence | [`check_release_tag.py`](../../scripts/check_release_tag.py), [`audit_source_dependencies.py`](../../scripts/audit_source_dependencies.py), and [`verify_supply_chain_evidence.py`](../../scripts/verify_supply_chain_evidence.py) enforce version agreement, exact source identities, advisory results, and consistent SBOM/license inventories. Preserve refusals and evidence provenance when inputs move to Rust packaging. |
| Bounded command execution | [`run_with_deadline.py`](../../scripts/run_with_deadline.py) retains process-group ownership through termination. Carry its deadline, descendant cleanup, and identity-reuse contracts into the Rust runner. |

Rust audit orchestration may call ecosystem-specific scanners. While a Python
reference or model environment is supported, keep its PyPI and pinned-source
audit coverage; Cargo evidence does not replace that coverage. Python needed
by those developer or CI checks is separate from the operator installation
path. The choice of an inference runtime remains a separate decision.

| Alternative | Consequence |
| --- | --- |
| Keep Python tooling | Lowest immediate migration cost and direct reuse of the current code and tests. It retains Python as an installation prerequisite, which conflicts with #150. |
| Rewrite the logic in shell | Can avoid a Python bootstrap, but puts structured metadata, rollback state, and process supervision into shell plus external parsers. That increases the quoting and recovery burden already visible in the integration tests. Thin dispatch wrappers retain shell's useful role. |
| Use Rust | Meets the installation constraint and shares the CLI's target language. It costs a port of the existing contracts, Rust serialization dependencies, build time, and a transition period with two implementations. It does not prove correct rollback or App Intents output by itself. |

Port one responsibility at a time, with failure cases observed against the
replacement before changing an entry point. Keep the Python implementation as
a reference until the corresponding checks pass. Prioritize installation and
bundle work in #150; move release/audit orchestration in separately reviewed
changes while preserving coverage for every supported dependency graph.
Do not claim a responsibility has moved to Rust while its entry point still
delegates to the Python implementation. The daemon feature policy above still
governs any daemon behavior changes needed by installation.

Revisit this choice if the requirement to install without Python is withdrawn
or a measured platform constraint prevents the Rust implementation from
preserving the bundle and recovery contracts. Revise the decision and #150
together before changing the target. Avoid a second port made only for language
uniformity. See the [delivery sequence](../../ROADMAP.md#build-and-install-tooling-after-the-rust-port).

## Model inference scope

Decision for [#117](https://github.com/flyingrobots/AI-TTS/issues/117): **the
Rust rewrite stops at the model worker boundary.** The Rust daemon will own
application behavior and worker supervision. Python model workers will retain
inference and G2P. Keep the Python Kokoro reference worker for Rust cutover;
a native inference engine is an optional later change. This decision selects
no Rust inference library and requires no model replacement.

The current daemon is Python. Its
[`ManagedEngine`](../../src/aitts/engines/managed.py) starts a persistent
[`aitts.model_worker`](../../src/aitts/model_worker.py) in a separate Python
environment and exchanges JSON-lines messages. That worker keeps the model
warm and returns WAV files or streamed PCM audio. The current daemon also
supports in-process adapters. This decision does not describe an implemented
Rust supervisor or remove those Python adapters.

The [guided-setup evidence](../testing-evidence/2026-10-01-local-model-setup.md)
records isolated runtimes and real output from Kokoro, Kokoro MLX, and
Chatterbox. The [worker tests](../../tests/test_managed_engine.py) check audio
transfer, offline restart, interrupted streams, and bounded failure with a
controlled producer. These establish a reusable process contract. They do not
establish quality parity for a native engine. The
[engine evaluation](engine-evaluation.md) gives the original local-model
rationale; its historical port reports are not current defect findings.

| Option | Consequence |
| --- | --- |
| Keep Python model workers | Preserves the reference inference and G2P path during the daemon port. It retains Python runtime installation, dependency audits, worker supervision, and pipe overhead. |
| Replace inference as part of the rewrite | Could remove Python from synthesis and simplify runtime delivery. It adds model, G2P, audio-quality, and distribution checks to the cutover requirements without completed comparison evidence. |

The first option limits the mandatory rewrite to application contracts.
Changing a language does not establish correct speech, lower latency, or
compatible distribution terms. The existing worker boundary also permits a
later engine replacement without another daemon rewrite.

[#133](https://github.com/flyingrobots/AI-TTS/issues/133) must preserve worker
audio and lifecycle behavior, and test supervision failures. After that prerequisite,
[#141](https://github.com/flyingrobots/AI-TTS/issues/141) may evaluate one
optional native Kokoro implementation within its five-day time box. Its
result does not block the daemon cutover. Before adoption:

- Pin the candidate, Python reference, model assets, voices, and text cases.
  Set duration tolerances and silence/level checks before the comparison.
- Compare complete output and pronunciation on the fixed English text set.
  Reject silent or truncated clips and material pronunciation regressions.
  Record a listening assessment; waveform measurements alone are insufficient.
- Record the supported scope and unresolved cases. A small English sample
  does not establish parity for other languages, voices, or Chatterbox.
- Review the actual code, model, G2P, and distribution dependencies and licences.
  Treat changed eSpeak linkage or bundling as a new distribution review.
  A Rust adapter and a process boundary do not settle licence obligations.

Keep the Python reference available for comparison and recovery. A successful
spike permits a reviewed optional adapter; it does not automatically change
the default engine. A later default change needs a recorded decision supported
by that evidence. If the evidence fails, retain the worker implementation.

This choice is compatible with [#150](https://github.com/flyingrobots/AI-TTS/issues/150):
the Rust installer must install and start the daemon without preinstalled
Python. Guided model setup must then obtain the private Python runtime and
model dependencies before speech. It must report setup failure and permit
retry. Installing the daemon does not mean a model is ready. Preserve the
existing rule against bundling or redistributing the Python environment;
guided setup obtains dependencies on the operator's machine. This is a port
requirement, not a claim that the current installer meets #150.

Reconsider the default only after a native candidate passes these checks, or
measured worker costs justify another scoped evaluation. Keep the worker
fallback until a replacement meets its acceptance criteria. See the
[roadmap sequence](../../ROADMAP.md#model-inference-scope).

## Input audio retention

Decision for [#124](https://github.com/flyingrobots/AI-TTS/issues/124): **keep
transcript text, not recorded input audio.** This is a constraint for the
planned listening feature, not a claim that a recognizer or transcript store
is implemented. It applies to microphone input, not to synthesized speech or
its existing audio cache. Transcript text retention remains governed by the
speech-history policy and is outside this decision.

The [README confidentiality contract](../../README.md#a-note-on-what-this-speaks)
treats text as sensitive by default. It also explains that audio spoken during
a call can enter another person's transcript. Captured audio adds information
that text does not need: the speaker's voice and background speech or sounds.
Keeping it for later diagnosis would create an additional sensitive record.

For the implementation, apply these rules:

- Start capture only through an explicit, expiring listen session. Permission
  to use the microphone does not itself start a session.
- Keep only bounded working buffers needed for active recognition. Release
  their audio when the transcript is final, or when the request is cancelled,
  the session expires, or recognition fails. A failed request does not grant
  permission to save a diagnostic recording.
- Do not write application-managed input-audio files, database blobs, caches,
  or audio payloads in diagnostic logs. Do not add a retention setting or a
  saved-audio reference to the transcript store. A backend that requires an
  input file needs a revised decision before integration; it must not add a
  temporary-file exception silently.
- After a crash, do not recover or replay captured audio. A new capture needs
  a new explicit request. Releasing working buffers is not a claim of secure
  memory erasure or control over operating-system swap and crash dumps.

| Option | Consequence |
| --- | --- |
| Text only, selected | Avoids an application-managed recording archive and its deletion lifecycle. A bad transcript cannot be diagnosed by replaying a saved input. Recognition must accept bounded working audio without an input file. |
| Optional audio retention, off by default | Can help diagnose a bad transcript. It needs a separate consent step, clear recording state, expiry, deletion, and protection against saving nearby speech without agreement. Those controls are not part of the current listening plan. |
| Audio retention on by default, with expiry | Makes replay available without another choice, but creates recordings before the user asks to keep them. Expiry limits duration; it does not prevent that collection or remove copies made while the recording exists. |

[#144](https://github.com/flyingrobots/AI-TTS/issues/144) must store final text,
session, and source without raw audio or a saved-input path. The listener and
recognizer work must verify the buffer lifecycle on finalization, cancellation,
expiry, failure, and process loss. Tests of the future implementation must
observe the storage and worker boundaries; this documentation decision is not
runtime proof that no audio reaches disk.

Reconsider only for a concrete need that text-only diagnosis cannot meet.
Keeping more requires a new consent step and a reviewed retention/deletion
design before implementation. Reducing retention remains the safer direction.
See the [listening sequence](../../ROADMAP.md#input-audio-retention).

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
| Packaging | source wheel/sdist, `uv tool`, ad-hoc-signed `.app`, generated launchd plist | Checkout-independent on the owner's machine, but deliberately not a notarized third-party package; the Python environment is never bundled |
| Lint / types / tests | `ruff` (all rules on), `mypy --strict`, `pytest` | House rule: maximal strictness, warnings promoted to errors |

The one genuinely uncomfortable dependency is transitive, and it is worse than the Piper situation flagged in [engine-evaluation §2](engine-evaluation.md#2-local-models): `misaki`'s G2P fallback arrives via `espeakng-loader`, which **bundles `libespeak-ng.dylib` (GPL-3.0) and loads it into the Python process**. That is dynamic linking, not mere aggregation. Verified against a working reference install (2026-09-01): `kokoro 0.9.4` and `misaki 0.9.4`, both Apache-2.0 by their own metadata, alongside `espeakng-loader 0.2.4` shipping the dylib inside the wheel, on `torch` 2.10.0 — the exact reference path this document proposes.

The dependency gate is now executable rather than an occasional manual scan.
CI exports the hashed `uv.lock` graph with the Kokoro extra, audits every
applicable macOS/Python 3.12 package, emits a cross-platform CycloneDX SBOM,
and reconciles the audit against installed license metadata. The isolated
2026-09-05 receipt found 104 applicable packages, zero known vulnerabilities,
and one unknown license (`espeakng-loader`); it also surfaced the GPLv3+ and
LGPL metadata already called out here. This inventory does not decide whether
redistribution is legally compatible.

What keeps this survivable: this project distributes source that depends on `kokoro`, never a bundled environment containing the dylib. The hard rule that follows — **AI-TTS must never vendor, bundle, or redistribute its Python environment** — is recorded here so the packaging row above reads as the project boundary, not merely a convenience. The local app bundle therefore contains only the native menu executable and metadata. Worth confirming during review whether the espeak fallback can be disabled outright, because the identifiers this tool speaks are heading for the pronunciation lexicon anyway ([architecture §8](architecture.md#8-the-engine-interface)).

Guided model setup (accepted as disclosed, 2026-10-01): the Kokoro and Kokoro MLX runtimes that setup installs contain `phonemizer-fork` (GPLv3+) and the `libespeak-ng` library (GPL-3.0) bundled by `espeakng-loader`, both pulled in through `misaki`. Setup downloads them from PyPI onto the user's own machine with hash-pinned requirements; AI-TTS still never redistributes them. For a guided runtime, they load only inside that model's separate worker process (`aitts.model_worker`, in its own private virtual environment under `model-runtimes`), not inside the daemon process, which talks to the worker over a JSON-lines pipe. The daemon's existing in-process Kokoro adapter, installed with the `kokoro` extra, still loads them in the daemon as described above. The redistribution rule above still applies to these runtimes.

## Menu-bar app: Swift 5.10+, SwiftUI in an AppKit shell

`NSStatusItem` + `NSPopover` as the shell, SwiftUI for the views inside it. The popover content in the mockups — lists, segmented modes, transport controls — is exactly what SwiftUI does cheaply, and the parts SwiftUI still fumbles on macOS (status items, popover behaviors, launch-at-login) stay in AppKit where they are one class each.

The Swift package has three dependency-directed targets. `AITTSApplication` is
a reusable library of public models, ports, and use cases with no AppKit,
SwiftUI, PDFKit, socket, or wire-format dependency. `AITTSMacAdapters` implements
its selected-document and speech-service ports using native file APIs and the
daemon's Unix socket. `AITTSMenuBar` owns presentation and composes those
libraries. The accepted OS integration is a sibling inbound-adapter target,
not code embedded in the presentation target.

The app subscribes to state events for live updates
([features 6.9](features.md#6-menu-bar-ui)) and issues the same ops any CLI
client would. No daemon logic leaks into it. If the daemon is not running, the
app says so and offers to start it — that is the whole extent of its privileged
knowledge.

Tooling: Swift Package Manager, no Xcode project file if avoidable; `swiftlint` and `swift-format` at maximal strictness; XCTest.

## Native OS integration: AppKit Services first

The accepted system-entry design uses APIs already native to the Swift/AppKit
client. It does not introduce an extension host, browser runtime, event-tap
helper, or second IPC protocol. The complete behavior and privacy decision is
in [`os-integration.md`](os-integration.md).

| Concern | Choice | Why |
|---|---|---|
| Selected text | AppKit Services provider plus generated `NSServices` metadata | The source app hands over only the invoked selection; no Accessibility trust or clipboard mutation |
| Selected file | A second AppKit Service receiving one file URL | Reuses `DocumentEnqueueing`; a Finder Sync extension would add privilege and duplicate a system capability |
| Service shortcut | User-assigned macOS Services shortcut | Avoids a global event tap and its monitoring permission |
| Menu fallback | `ApplicationServices` Accessibility APIs behind `SelectedTextReaderPort` | Best-effort access for nonparticipating hosts, queried once after explicit invocation |
| Clipboard fallback | Read-only AppKit pasteboard adapter | Works after an explicit copy and never saves, replaces, or restores clipboard state |
| Automation | `AppIntents` in the menu executable | Typed actions for custom macOS Shortcuts reuse existing application ports; compiler metadata is generated and validated before signing |

The Swift package has a sibling `AITTSMacEntryPoints` target for the Services
provider and explicit Accessibility and clipboard adapters. It depends inward
on `AITTSApplication`; the `AITTSMenuBar` executable remains the composition
root that registers the provider and injects `EnqueueSelection` and
`EnqueueDocument`. `AITTSApplication` imports no AppKit or ApplicationServices
types, and `AITTSMacAdapters` continues to own outbound file/PDF and Unix-socket
translation.

The hand-built app bundle is a load-bearing part of this choice. The builder
generates both Service dictionaries under `NSServices`, performs Swift constant
extraction for the App Intents, validates the exact semantic inventory under
`Metadata.appintents`, and signs only afterward. This proves SwiftPM
compilation, manual bundle assembly, and signing. Installed Services discovery,
App Intents indexing, and real invocations are separate acceptance gates. The
local installed bundle is indexed; a real Shortcuts invocation remains open.
Merely compiling an `AppIntent` type is not distribution proof.

## CLI client: part of the daemon's Python package

`ai-tts say "text" --sensitivity public`, `ai-tts wait <id>`, `ai-tts pause` — a thin argparse wrapper over the socket, shipped in the same package as the daemon so one install produces both. It exits 0 only when the daemon acknowledged the operation, and `wait` exists for callers that need "was actually spoken" ([features 8.5](features.md#8-agent-facing-client-interface)). Agents that want more than the CLI offers speak NDJSON to the socket directly; the protocol is the interface, the CLI is a convenience.

## Rejected options

| Option | What it offered | Why it lost |
|---|---|---|
| **Electron / web tray app** | One language everywhere, familiar UI stack | ~200 MB and a Chromium process for a 360×480 popover. The mockups specify native metrics that a webview only imitates. Wrong tool by an order of magnitude |
| **Tauri** | Native-ish footprint, web UI | Still a webview for the popover, plus a Rust toolchain — a third language whose only job would be hosting the other two |
| **All-Swift** (daemon too, Kokoro via CoreML) | One language, simpler packaging | The original choice lacked reference and audio-quality comparison evidence for the replacement engine. The inference decision above keeps such evidence as a gate; it makes no current defect claim about CoreML. |
| **All-Python** (tray via `rumps`/PyObjC) | One language, no Swift | `rumps` does menus, not the popover UI the mockups specify. Full PyObjC AppKit is writing AppKit with worse tooling and no Interface Builder escape hatch |
| **Node/TypeScript daemon** (`kokoro-js` on ONNX Runtime) | One repo-wide JS toolchain | Community ONNX port rather than the reference implementation, and a second runtime to supervise. Nothing else in the design wants Node |
| **Rust daemon, Python engine subprocess** | Separate application and model runtimes | Originally rejected because of process and supervision costs. Superseded by [#117](#model-inference-scope): guided setup already keeps models warm in Python workers. Preserve and test that boundary during the Rust port. |
| **gRPC / protobuf IPC** | Typed schema, codegen | [Architecture §5](architecture.md#5-ipc) chose NDJSON over UDS deliberately: inspectable with `nc`, no codegen step for agent authors, and the message set is small. A schema can be reintroduced as JSON Schema validation without changing the wire |
| **Finder Sync extension for “Read File”** | Direct Finder integration and custom contextual UI | A file Service already receives an explicit Finder selection without an extension process or a second document pipeline |
| **Synthetic Command-C selection capture** | Apparent compatibility with any copyable view | Mutates another app and the global clipboard, races focus and other clipboard clients, and violates the explicit-input boundary |
| **Accessibility as the default** | One menu-bar command independent of Services participation | Requires broad trust, exposes selected text unevenly, and invites background observation; retained only as an explicit fallback |

## What would change these answers

- **The espeak-ng fallback cannot be cleanly disabled or isolated.** Then the G2P path needs re-examination before anything ships, because a GPL runtime dependency in an Apache repo is exactly the contamination the licence gate exists to catch.
- **PyTorch-on-MPS synthesis proves materially slower than the reported figures.** The engine-evaluation numbers are secondary-source and unverified. If real-world synthesis cannot stay ahead of playback, the MLX port gets promoted from optimization to requirement, and its silent-output report gets investigated rather than avoided.
- **Distribution beyond this one machine.** Signed, notarized bundles change the packaging answer entirely and strengthen the all-Swift case.
- **SwiftUI's status-item support matures** to where the AppKit shell is dead weight. Cheap to adopt; nothing depends on the shell's internals.

## What I could not establish

- **Actual synthesis throughput of `kokoro` on PyTorch/MPS on the target machine.** Every performance figure inherited from the engine evaluation is `unverified`. Fix: a ten-line spike script against a reference environment, timed, before the queue design is validated against real numbers.
- **Whether `sounddevice` supports pause-and-resume at a sample offset cleanly on CoreAudio**, which within-utterance rewind ([architecture §10.1](architecture.md#10-decisions-taken-at-implementation)) would need. If it does not, the fallback is chunk-granular seeking, which is another argument for utterance-level rewind in v1.
- **Whether `misaki` operates fully without espeak-ng present.** The reference install has `espeakng-loader` present, so it demonstrates the path *with* the fallback, not without it. This is the licence question above wearing its practical clothes.
