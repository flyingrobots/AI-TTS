# Code Quality Audit Report: flyingrobots/AI-TTS
**Commit**: `e2c7706` | **Weight Profile**: `Fintech` | **Status**: **🟢 PRODUCTION READY**

## Level 3: Executive Summary
* **Overall Quality Score**: `3.78 / 5.0`
* **Operational Readiness Check**: 🟢 PRODUCTION READY

> [!NOTE]
> All critical security and reliability gatekeepers passed the minimum safety threshold of `3.0`.

### Key Takeaways
* **Top Performing Areas**: `Security` (Score: `4.64`), `Developer Experience` (Score: `4.58`), `Maintainability` (Score: `4.43`)
* **Most Critical Areas**: `Cloud-Native` (Score: `2.17`), `Observability` (Score: `2.33`), `Project Health` (Score: `2.67`)

## Level 2: Tech Lead Summary
| Category | Weighted Score | Trend | Operational Weight | Status |
| :--- | :--- | :---: | :--- | :--- |
| **Accessibility (UI)** | `3.00 / 5.0` | → | `0.5` | 🟡 Needs Attention |
| **Cloud-Native** | `2.17 / 5.0` | → | `1.0` | 🔴 Critical |
| **Code Maturity** | `3.50 / 5.0` | → | `1.5` | 🟡 Needs Attention |
| **Code UX** | `4.33 / 5.0` | → | `1.0` | 🟢 Healthy |
| **Data Privacy** | `4.17 / 5.0` | → | `2.5` | 🟢 Healthy |
| **Developer Experience** | `4.58 / 5.0` | → | `0.8` | 🟢 Healthy |
| **Maintainability** | `4.43 / 5.0` | → | `1.0` | 🟢 Healthy |
| **Observability** | `2.33 / 5.0` | → | `1.5` | 🔴 Critical |
| **Performance** | `4.00 / 5.0` | → | `1.5` | 🟢 Healthy |
| **Project Health** | `2.67 / 5.0` | → | `1.0` | 🟡 Needs Attention |
| **Security** | `4.64 / 5.0` | → | `3.0` | 🟢 Healthy |

### Accessibility (UI) Rationale
Adequate by accident rather than by design. The SwiftUI views inherit implicit semantics and carry 24 `.help()` tooltips, which VoiceOver can surface, but there is not one explicit accessibilityLabel, accessibilityValue or accessibilityHint anywhere in the client. The transport row uses `.labelStyle(.iconOnly)`, which is exactly the pattern that drops a control's text out of the accessibility tree.

Two gaps matter more than the rest. There is only one keyboard shortcut in the entire app, so pausing or stepping a chunk mid-sentence means reaching for the trackpad — poor for the dialogue workflow this tool is built around. And the interruption notice, the one message the app must deliver unprompted, is not announced as a live region, so a screen-reader user is not told that playback stopped because their microphone went live. For a speech-accessibility tool, that is a pointed omission rather than a cosmetic one.

### Cloud-Native Rationale
Scored low, and correctly so, against a rubric this project is not trying to satisfy. The daemon is a stateful singleton by design: exactly one process may own the audio output device, which is the entire fix for the overlapping-speech failure the project exists to solve, and its queue is durable across restarts on purpose. It links CoreAudio and PortAudio, binds a Unix socket inside the user's Library directory, and ships as a codesigned .app plus a launchd agent. A container has no speakers.

The genuine finding hiding inside the rubric miss is smaller and worth doing: these deviations are not written down as decisions. Configuration does come from the environment, and the process is a single foreground worker, but logs go to a bounded file rather than stdout because launchd would route stdout to an unbounded one — a deliberate confidentiality trade-off that currently exists only as behaviour, not as a recorded choice.

### Code Maturity Rationale
The change record is excellent and the release machinery is missing. CHANGELOG.md follows Keep a Changelog closely and describes changes in terms of the failure they fix, which is rarer and more useful than a list of commit subjects. Semantic versioning is declared and the version is pinned in pyproject.toml.

Against that, nothing identifies a build. There is no git tag in 571 commits, no published release, and no way to ask an installed binary which commit it came from. Every install is a hand-run sequence of three scripts, and CI builds no artifact even though the build scripts exist and work. The remote is empty, so none of this has ever been exercised end to end.

### Code UX Rationale
The wire protocol is small, uniform and typed: every response carries `ok`, failures are typed errors rather than empty responses, and the public schemas forbid extra fields, so a drifting daemon is caught rather than tolerated. Predictability is the strongest property here — the utterance state machine permits no transition that is not named in one table, and the CLI's exit codes are truthful in a way most tools are not: exit 0 means accepted onto the queue, and only `--wait` returns 0 for actually played.

Error handling is solid at the boundary and slightly uneven inside it. A bad request cannot kill the daemon, the playback loop is supervised with backoff, and device failures settle the utterance as Failed with the position reached. The op surface has grown to 25 though, and `assign_voice` overloads an omitted field to mean release, which is compact but not self-describing.

### Data Privacy Rationale
The posture is coherent and, as of this audit, actually true. Every utterance carries a sensitivity that defaults to confidential, so a caller leaks by explicitly declaring text public rather than by forgetting a flag, and non-public text can never reach a non-local engine. State and cache directories are normalized to 0700 and files to 0600, symlinked state roots are refused, and diagnostics carry no speech text, source labels or paths. There is no telemetry.

One real leak existed until it was fixed during this session: the engine took its upstream defaults and resolved the model config, the weights and every voice pack through a remote model host on each load — 49 such requests appeared in one session's log, each naming the exact voice and the moment it spoke. Assets now resolve from the local cache first, verified at zero requests. Speech text is stored in plaintext in the local SQLite history, which is the correct trade for a history feature on an owner-only file, but it is worth knowing that history retention is permanent by default.

### Developer Experience Rationale
The feedback loop is the standout: the Python suite finishes in about 7 seconds against a self-enforced 30-second budget that fails the run if exceeded, and the Swift suite in under 0.2 seconds. Both are one command. Test doubles are first-class rather than retrofitted — FakeSink detects overlapping playback, FakeEngine, FakeAudioDevice, FakeInputActivity and a deterministic playback scheduler with explicit interleaving checkpoints all ship in the source tree, which is why a real audio device and a real model are not needed to test the parts that own them.

Onboarding is helped enormously by docs/design, but the domain is genuinely subtle: two queues that exist for different reasons, a nested clip queue inside single entries, and a sensitivity field that fails closed. A newcomer will need the architecture document, not just the README. Two languages is the honest cost of a native menu-bar client, and the split is clean rather than incidental.

### Maintainability Rationale
The code reads like it was written to be read. Every module opens with a docstring naming the architecture section it implements, and comments explain why a decision was taken rather than restating the code — the playback sink's device-reopen loop and the input-activity edge detector both carry the reasoning that makes them look strange at first glance. Ruff runs with `select = ["ALL"]` and mypy with `strict = true`, both clean, and both enforced by a pre-commit hook rather than by hope. Measured complexity is genuinely low: mean 2.70 across 423 functions, median 2, and only four functions above 8. Duplication is 1.15%, and inspecting the hits shows they are shared schema import lists, not copied logic.

The one real weakness is size concentration. daemon.py routes 25 wire ops and also owns settings validation, voice resolution, cache enforcement and the input watcher; store.py covers both queues, history, settings and the voice register; Views.swift is a single 900-line file. Nothing there is wrong, but four files now hold most of the reasons this project will change, and the ports needed to split them already exist.

### Observability Rationale
This is the weakest area, and unevenly so. Logging is deliberate and well-built for its threat model: one bounded 2 MiB rotating file at mode 0600, static event codes only, an allowlist of non-content fields, exception payloads suppressed, and a test that walks the AST of every package diagnostic to prove no unapproved dynamic field can be logged. That is stronger than most production services.

Metrics and tracing are effectively absent. Terminal-state counts are the only aggregate exposed, so the architecture's central claim — that the queue rather than the engine governs perceived responsiveness — cannot be verified against a running daemon. There is no correlation identifier tying one utterance's journey across submit, synthesis and playback, which makes a stuck clip a SQLite investigation. Distributed tracing would be the wrong tool for a single process; a per-utterance correlation id in the existing events would close most of the gap cheaply.

### Performance Rationale
Sound, with the right things measured and the wrong things left alone. The two-queue split is the load-bearing performance decision: synthesis is parallel and ahead-of-time, playback is serial and real-time, so a backed-up queue drains at playback speed rather than synthesis speed. Audio is streamed in 2048-frame blocks rather than materialized, generated audio is cached so a replay costs nothing, and the cache is capped with terminal-audio eviction that will not evict what a queued clip still needs.

SQLite access is parameterized and indexed on the fields actually filtered (state and order_key) with WAL enabled. Resource use is dominated by holding the model warm in memory, which is the explicit trade for first-clip latency. The polling that remains is cheap and was measured rather than assumed: the audio-device check costs 24 microseconds and the input-activity check 0.73 milliseconds, against loops running at 85 milliseconds and 150 milliseconds.

### Project Health Rationale
Test maintainability is a genuine strength. Every test declares exactly one size class and a named oracle, enforced by a collection hook that fails the run on a missing marker, so a test that cannot say which authority it derives from does not run. 331 Python and 83 Swift tests, written test-first in visible pairs throughout the history.

The rest of the category is thin. All 571 commits are by one author, with no second reviewer and no branch protection — because the remote has no branches. More fixable: there is no issue tracking at all, and the only defect record is `.claude/bad_code.md`, which is gitignored and therefore invisible to any collaborator or future session. Known open items live in prose inside an untracked file, which is the one place they cannot be picked up.

### Security Rationale
The strongest category, and it earns it through boundaries rather than through features. The IPC surface is a Unix socket created 0600 — a listening port cannot be exposed by accident, which is the stated reason for the choice — with a 1 MiB request cap, strict typed schemas that forbid unknown fields, and internal failures that answer "internal error; see daemon log" instead of leaking a traceback. Document acquisition is bounded before it reaches the daemon at 512 KiB of text, or 32 MiB and 500 pages and 512 KiB of extracted text for PDFs.

Supply chain is unusually rigorous for a project this size: CI exports a hash-pinned requirements set, runs pip-audit in strict mode with `--require-hashes`, emits a CycloneDX SBOM, inventories licenses, and then runs a verification script that cross-checks every retained report. Actions are pinned by commit SHA with a read-only token and non-persisted checkout credentials. There are no secrets to manage and none committed. Threat modeling is real: architecture section 9 argues its way to putting the confidentiality guard on the text rather than on the engine, and records the sniffer question it deliberately left unresolved.

## Level 1: Developer Assessment Matrix
| Category | Metric | Type | Score | Trend | File / Location | Status | Findings / Action Items |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| Accessibility (UI) | Keyboard Navigability | Qualitative | `3.00` | → | [clients/menubar/Sources/AITTSMenuBar/Views.swift:795](clients/menubar/Sources/AITTSMenuBar/Views.swift#L795) | ✅ Pass | The popover has one explicit keyboardShortcut in the whole app (clients/menubar/Sources/AITTSMenuBar/Views.swift) and the transport is mouse-driven. There is no key path to pause, skip, or step chunks while the popover is open, and no global hotkey, so the fastest controls for a dialogue workflow require reaching for the trackpad. |
| Accessibility (UI) | Screen Reader Friendliness | Qualitative | `3.00` | → | [clients/menubar/Sources/AITTSMenuBar/Views.swift:60](clients/menubar/Sources/AITTSMenuBar/Views.swift#L60) | ✅ Pass | VoiceOver gets only what SwiftUI infers. Live regions are the specific gap: the interruption notice, the chunk counter and the caption panel all change while the popover is open, and none are marked as accessibility-announcing, so a screen-reader user is not told that playback stopped because their microphone went live. |
| Accessibility (UI) | WCAG Compliance | Qualitative | `3.00` | → | [clients/menubar/Sources/AITTSMenuBar/Views.swift:323](clients/menubar/Sources/AITTSMenuBar/Views.swift#L323) | ✅ Pass | No accessibility audit has been performed on the menu-bar UI. Views.swift relies on implicit SwiftUI semantics with 24 .help() tooltips and no explicit accessibilityLabel, accessibilityValue or accessibilityHint anywhere in clients/menubar/Sources. Icon-only transport buttons use .labelStyle(.iconOnly), which discards the text label from the accessibility tree. |
| Cloud-Native | 12-Factor Compliance | Qualitative | `3.00` | → | [src/aitts/paths.py:14](src/aitts/paths.py#L14) | ✅ Pass | Partly by design, partly not. Config is read from the environment (AI_TTS_HOME and AI_TTS_SOCKET in src/aitts/paths.py) and the process is a single foreground worker, but logs are written to a rotating file rather than emitted to stdout as an event stream, because the launch agent routes stdout and stderr to /dev/null to keep speech payloads out of unbounded logs. |
| Cloud-Native | Container-friendliness | Qualitative | `1.50` | → | [scripts/render_launch_agent.py:63](scripts/render_launch_agent.py#L63) | ❌ Fail | The daemon cannot be containerized in any useful way. It binds a Unix socket in the user's Library directory, links CoreAudio and PortAudio to own a physical output device, reads CoreAudio input activity, and ships a codesigned .app bundle (scripts/build_app_bundle.py). It is a macOS desktop agent by construction. |
| Cloud-Native | Statelessness | Qualitative | `2.00` | → | [docs/design/architecture.md:30](docs/design/architecture.md#L30) | ❌ Fail | The daemon is deliberately stateful: it owns a SQLite queue at ~/Library/Application Support/ai-tts/state.db and is the sole owner of the audio output device (src/aitts/playback.py). This is the architecture's central fix for overlapping speech (docs/design/architecture.md sections 2 and 4), not an oversight. |
| Code Maturity | Automated Deployment | Qualitative | `3.00` | → | [.github/workflows/ci.yml:1](.github/workflows/ci.yml#L1) | ✅ Pass | A Makefile now wraps build, install and the agent integrations, and refuses to run off macOS, so a clone reaches a running daemon in one command. What is still absent is release automation: no workflow builds or attaches the wheel, the codesigned app bundle or the launch agent to a tag, there is no tag, and nothing has been pushed to the remote, which is empty. |
| Code Maturity | Change-log/Release Notes | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Code Maturity | Versioning | Qualitative | `3.00` | → | [pyproject.toml:7](pyproject.toml#L7) | ✅ Pass | pyproject.toml pins version 0.1.0 and CHANGELOG.md declares semantic versioning, but no git tag exists anywhere in 571 commits and no release has been published. The version is therefore unverifiable from the repository, and README calls v0.1.0 a release candidate with no artifact behind it. |
| Code UX | API Simplicity | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Code UX | Error Handling Robustness | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Code UX | Predictability | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Data Privacy | Consent Management | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Data Privacy | Data Anonymization | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Data Privacy | GDPR/CCPA Compliance | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Developer Experience | Build & Test Simplicity | Qualitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Developer Experience | Conceptual Cohesion | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Developer Experience | Feedback Loop Speed | Qualitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Developer Experience | Onboarding Effort | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Developer Experience | Technology Diversity | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Developer Experience | Tooling & Automation | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Code Duplication | Quantitative | `4.78` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Cyclomatic Complexity | Quantitative | `4.57` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Discoverability | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Documentation Quality | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Lines of Code (LoC) | Quantitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Readability | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | SRP Violations (4 found) | Qualitative | `2.50` | → | [src/aitts/daemon.py:324](src/aitts/daemon.py#L324) | ❌ Fail | Size concentration got worse, not better. daemon.py is now 1047 lines and still routes every wire op while owning settings validation, voice resolution and reconciliation, cache enforcement and the input watcher. store.py is 941 lines across both queues, history, settings and the voice register. playback.py is 927 lines covering the sink, the transport, chunk navigation and the listener interrupt. Views.swift has grown to 1169 lines holding every popover surface. Four files hold most of the reasons this project will change, and remediation work added to them rather than splitting them. |
| Maintainability | Test-Double Friendliness | Qualitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Maintainability | Uses Dependency Injection | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Observability | Logging | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Observability | Metrics | Qualitative | `1.00` | → | [src/aitts/daemon.py:829](src/aitts/daemon.py#L829) | ❌ Fail | No application metrics are exposed. The status op reports terminal-state counts (src/aitts/daemon.py:_op_status) but nothing measures synthesis latency, queue depth over time, cache hit rate, or how often playback fails on the device, so the queue-vs-engine performance claim in docs/design/architecture.md cannot be checked against a running system. |
| Observability | Tracing | Qualitative | `1.50` | → | [src/aitts/adapters/diagnostic_logging.py:1](src/aitts/adapters/diagnostic_logging.py#L1) | ❌ Fail | No request correlation exists. An utterance passes through submit, segmentation, a synthesis worker, the playback controller and the sink, and the only thread tying those together is the utterance id, which the bounded diagnostic log deliberately does not record (src/aitts/adapters/diagnostic_logging.py). Debugging a stuck clip means reading state out of SQLite. |
| Performance | Algorithmic Complexity | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Performance | Database Queries | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Performance | Memory Management | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Performance | Resource Utilization | Qualitative | `4.00` | → | N/A | ✅ Pass | No findings recorded. |
| Project Health | Bus Factor | Qualitative | `1.00` | → | [CONTRIBUTING.md:1](CONTRIBUTING.md#L1) | ❌ Fail | Every commit is by a single author, with no second contributor, reviewer or maintainer named anywhere. CONTRIBUTING.md exists but describes no review process, and the remote has no branch protection because the remote has no branches. Substantial architectural reasoning lives in docs/design, which is unusually thorough but still single-sourced. |
| Project Health | Issue & Bug Management | Qualitative | `2.00` | → | [docs/standards/testing-profile.md:1](docs/standards/testing-profile.md#L1) | ❌ Fail | There is no issue tracking. The GitHub remote is empty so no issues exist, .github carries no issue or pull-request templates, and the only running defect record is an agent-local file excluded by .gitignore, so it is invisible to any collaborator. Remaining open items live as prose inside docs/standards/testing-profile.md rather than as tracked work. |
| Project Health | Test Maintainability | Qualitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Compliance with Standards | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Dependency Audit | Qualitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Error Handling | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Input Validation | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Secrets Management | Qualitative | `5.00` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Threat Modeling | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |
| Security | Use of Secure Libraries | Qualitative | `4.50` | → | N/A | ✅ Pass | No findings recorded. |

## Level 4: Prioritized Action Items
### 🚨 CRITICAL: Observability - Metrics (Score: `1.00 / 5.0`)
* **Description**: No application metrics are exposed. The status op reports terminal-state counts (src/aitts/daemon.py:_op_status) but nothing measures synthesis latency, queue depth over time, cache hit rate, or how often playback fails on the device, so the queue-vs-engine performance claim in docs/design/architecture.md cannot be checked against a running system.
* **Impact**: Medium (the design's central claim, that the queue and not the engine governs responsiveness, is unmeasured in production)
* **Effort**: Low (the store already records every timestamp needed; expose a metrics op that aggregates them)
* **Reference**: [https://prometheus.io/docs/practices/instrumentation/](https://prometheus.io/docs/practices/instrumentation/)

### 🚨 CRITICAL: Project Health - Bus Factor (Score: `1.00 / 5.0`)
* **Description**: Every commit is by a single author, with no second contributor, reviewer or maintainer named anywhere. CONTRIBUTING.md exists but describes no review process, and the remote has no branch protection because the remote has no branches. Substantial architectural reasoning lives in docs/design, which is unusually thorough but still single-sourced.
* **Impact**: High (the project stops entirely if the author does, and no one else can approve a change)
* **Effort**: High (organisational, not technical)
* **Reference**: [https://en.wikipedia.org/wiki/Bus_factor](https://en.wikipedia.org/wiki/Bus_factor)

### 🚨 CRITICAL: Observability - Tracing (Score: `1.50 / 5.0`)
* **Description**: No request correlation exists. An utterance passes through submit, segmentation, a synthesis worker, the playback controller and the sink, and the only thread tying those together is the utterance id, which the bounded diagnostic log deliberately does not record (src/aitts/adapters/diagnostic_logging.py). Debugging a stuck clip means reading state out of SQLite.
* **Impact**: Low-Medium (single-process and single-machine, so distributed tracing is not the right tool, but there is no correlation at all today)
* **Effort**: Low (a per-utterance span id in structured events, not OpenTelemetry)
* **Reference**: [https://opentelemetry.io/docs/concepts/signals/traces/](https://opentelemetry.io/docs/concepts/signals/traces/)

### 🚨 CRITICAL: Cloud-Native - Container-friendliness (Score: `1.50 / 5.0`)
* **Description**: The daemon cannot be containerized in any useful way. It binds a Unix socket in the user's Library directory, links CoreAudio and PortAudio to own a physical output device, reads CoreAudio input activity, and ships a codesigned .app bundle (scripts/build_app_bundle.py). It is a macOS desktop agent by construction.
* **Impact**: None as designed (a container has no speakers; the score reflects the rubric, not a defect)
* **Effort**: N/A
* **Reference**: [https://12factor.net/](https://12factor.net/)

### 🚨 CRITICAL: Cloud-Native - Statelessness (Score: `2.00 / 5.0`)
* **Description**: The daemon is deliberately stateful: it owns a SQLite queue at ~/Library/Application Support/ai-tts/state.db and is the sole owner of the audio output device (src/aitts/playback.py). This is the architecture's central fix for overlapping speech (docs/design/architecture.md sections 2 and 4), not an oversight.
* **Impact**: None as designed (a stateless replica set cannot serialize one machine's speakers; the score reflects the rubric, not a defect)
* **Effort**: N/A (making this stateless would delete the product's reason to exist)
* **Reference**: [https://12factor.net/processes](https://12factor.net/processes)

### 🚨 CRITICAL: Project Health - Issue & Bug Management (Score: `2.00 / 5.0`)
* **Description**: There is no issue tracking. The GitHub remote is empty so no issues exist, .github carries no issue or pull-request templates, and the only running defect record is an agent-local file excluded by .gitignore, so it is invisible to any collaborator. Remaining open items live as prose inside docs/standards/testing-profile.md rather than as tracked work.
* **Impact**: Medium-High (known defects are recorded somewhere no collaborator and no future session can see)
* **Effort**: Low
* **Reference**: [https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests)

### ⚠️ HIGH: Maintainability - SRP Violations (4 found) (Score: `2.50 / 5.0`)
* **Description**: Size concentration got worse, not better. daemon.py is now 1047 lines and still routes every wire op while owning settings validation, voice resolution and reconciliation, cache enforcement and the input watcher. store.py is 941 lines across both queues, history, settings and the voice register. playback.py is 927 lines covering the sink, the transport, chunk navigation and the listener interrupt. Views.swift has grown to 1169 lines holding every popover surface. Four files hold most of the reasons this project will change, and remediation work added to them rather than splitting them.
* **Impact**: Medium (each file is a merge-conflict magnet and the daemon's op table is now the widest surface in the codebase)
* **Effort**: Medium (extract cohesive collaborators; the ports already exist to hang them from)
* **Reference**: [https://en.wikipedia.org/wiki/Single-responsibility_principle](https://en.wikipedia.org/wiki/Single-responsibility_principle)

### ⚠️ HIGH: Cloud-Native - 12-Factor Compliance (Score: `3.00 / 5.0`)
* **Description**: Partly by design, partly not. Config is read from the environment (AI_TTS_HOME and AI_TTS_SOCKET in src/aitts/paths.py) and the process is a single foreground worker, but logs are written to a rotating file rather than emitted to stdout as an event stream, because the launch agent routes stdout and stderr to /dev/null to keep speech payloads out of unbounded logs.
* **Impact**: Low (the log deviation is a deliberate confidentiality trade-off; the missing piece is that it is not written down)
* **Effort**: Low (document the deviation; optionally allow stdout logging for foreground development)
* **Reference**: [https://12factor.net/logs](https://12factor.net/logs)

### ⚠️ HIGH: Accessibility (UI) - WCAG Compliance (Score: `3.00 / 5.0`)
* **Description**: No accessibility audit has been performed on the menu-bar UI. Views.swift relies on implicit SwiftUI semantics with 24 .help() tooltips and no explicit accessibilityLabel, accessibilityValue or accessibilityHint anywhere in clients/menubar/Sources. Icon-only transport buttons use .labelStyle(.iconOnly), which discards the text label from the accessibility tree.
* **Impact**: Medium (a speech-accessibility tool that is itself hard to operate without sight is a pointed failure)
* **Effort**: Low (add explicit labels and values to the transport controls and progress views)
* **Reference**: [https://developer.apple.com/documentation/accessibility/](https://developer.apple.com/documentation/accessibility/)

### ⚠️ HIGH: Accessibility (UI) - Keyboard Navigability (Score: `3.00 / 5.0`)
* **Description**: The popover has one explicit keyboardShortcut in the whole app (clients/menubar/Sources/AITTSMenuBar/Views.swift) and the transport is mouse-driven. There is no key path to pause, skip, or step chunks while the popover is open, and no global hotkey, so the fastest controls for a dialogue workflow require reaching for the trackpad.
* **Impact**: Medium (a listener interrupted mid-sentence wants a key, not a menu-bar click)
* **Effort**: Low for in-popover shortcuts; Medium for a global hotkey (needs an event tap and its own permission)
* **Reference**: [https://developer.apple.com/design/human-interface-guidelines/keyboards](https://developer.apple.com/design/human-interface-guidelines/keyboards)

### ⚠️ HIGH: Accessibility (UI) - Screen Reader Friendliness (Score: `3.00 / 5.0`)
* **Description**: VoiceOver gets only what SwiftUI infers. Live regions are the specific gap: the interruption notice, the chunk counter and the caption panel all change while the popover is open, and none are marked as accessibility-announcing, so a screen-reader user is not told that playback stopped because their microphone went live.
* **Impact**: Medium (the interrupt notice is the one message in the app that must reach the user unprompted)
* **Effort**: Low
* **Reference**: [https://developer.apple.com/documentation/swiftui/view-accessibility](https://developer.apple.com/documentation/swiftui/view-accessibility)

### ⚠️ HIGH: Code Maturity - Versioning (Score: `3.00 / 5.0`)
* **Description**: pyproject.toml pins version 0.1.0 and CHANGELOG.md declares semantic versioning, but no git tag exists anywhere in 571 commits and no release has been published. The version is therefore unverifiable from the repository, and README calls v0.1.0 a release candidate with no artifact behind it.
* **Impact**: Medium (nothing identifies which commit any installed build came from)
* **Effort**: Low (tag the release commit and surface the version through the CLI)
* **Reference**: [https://semver.org/](https://semver.org/)

### ⚠️ HIGH: Code Maturity - Automated Deployment (Score: `3.00 / 5.0`)
* **Description**: A Makefile now wraps build, install and the agent integrations, and refuses to run off macOS, so a clone reaches a running daemon in one command. What is still absent is release automation: no workflow builds or attaches the wheel, the codesigned app bundle or the launch agent to a tag, there is no tag, and nothing has been pushed to the remote, which is empty.
* **Impact**: Medium (every install is a manual, unreproducible ceremony)
* **Effort**: Medium (a tag-triggered release job reusing the existing build scripts)
* **Reference**: [https://docs.github.com/en/actions/deployment/about-deployments](https://docs.github.com/en/actions/deployment/about-deployments)


## Level 5: Ready-to-Run Mitigation Prompts
Copy-paste ready prompts an LLM coding agent can use to remediate each flagged flaw directly.

### 🚨 Observability - Metrics (Score: `1.00 / 5.0`)
```
Add a `metrics` op to src/aitts/daemon.py that returns counters and latency summaries derived from the store: synthesis wait (submitted_at to Ready), playback wait (Ready to Playing), synthesis duration, per-state counts, cache bytes against the configured cap, and a count of playback device failures. Add a matching PublicSchema in src/aitts/application/schemas.py, a `list_speech_metrics` MCP tool, and an `ai-tts metrics` CLI command so the tray, CLI and agents all reach it. Write the tests first in a new tests/test_metrics.py with a size marker and a named oracle, then re-run `uv run pytest`.
```

### 🚨 Project Health - Bus Factor (Score: `1.00 / 5.0`)
```
Reduce the knowledge-transfer half of this rather than pretending to fix the staffing half. Add a docs/design/onboarding.md that walks a new maintainer through one utterance end to end, naming the exact files it passes through: cli.py submit, ipc.py dispatch, store.py submit, segmentation.py, synthesis.py claim and finish, playback.py begin_segment, and the sink. Link it from README's design-documents list and from CONTRIBUTING.md. Then extend CONTRIBUTING.md with the review expectation that applies today, even for a single maintainer: which checks must pass before merge and what a reviewer is expected to look at.
```

### 🚨 Observability - Tracing (Score: `1.50 / 5.0`)
```
Do not add OpenTelemetry; this is a single-process local daemon. Instead add a short correlation id to each utterance at submit in src/aitts/store.py (a 8-hex-character token, distinct from the utterance id so it is not client-identifying), and include it as a `trace=` field in the existing static-event diagnostics emitted at submit, synthesis claim, synthesis finish, playback start and playback end. Add `trace` to the allowlist in tests/test_diagnostic_logging.py's allowed_dynamic_fields, and assert the field never contains speech text. Re-run `uv run pytest`.
```

### 🚨 Cloud-Native - Container-friendliness (Score: `1.50 / 5.0`)
```
No code change. Document the target instead: state in README's Using it section that AI-TTS is a per-user macOS desktop daemon distributed as a launchd agent plus a codesigned app bundle, and that container images are explicitly not a supported deployment target because the process must own a physical audio device. That converts a rubric miss into a stated boundary.
```

### 🚨 Cloud-Native - Statelessness (Score: `2.00 / 5.0`)
```
No code change. Record the deviation instead: add a short subsection to docs/design/architecture.md under section 4 stating that the daemon is intentionally a stateful singleton because exactly one process may own the audio device and the queue is durable across restarts, and that horizontal statelessness is therefore out of scope. Cross-reference it from the section 10 decisions list so a future audit reads it as a decision rather than a gap.
```

### 🚨 Project Health - Issue & Bug Management (Score: `2.00 / 5.0`)
```
Move the tracked-defect record into the repository. Create docs/backlog/ containing one Markdown file per known open item, migrating the still-open entries from .claude/bad_code.md (the device-error wedge, history search, cache eviction, retry on failed rows, drag reorder, and the elapsed-time-ignores-abandoned-chunks note) with a title, the evidence path and line, and the reason it is still open. Add .github/ISSUE_TEMPLATE/bug_report.md and feature_request.md, plus .github/pull_request_template.md that requires the test-first pairing and the passing checks this repo already enforces. Leave .claude/ gitignored for session scratch only.
```

### ⚠️ Maintainability - SRP Violations (Score: `2.50 / 5.0`)
```
Split src/aitts/daemon.py so the Daemon class only routes requests and owns lifecycle. Extract three collaborators into src/aitts/application/: a SettingsService holding _apply_settings and every _apply_*_setting plus _settings_values; a VoiceRegistry holding _resolve_voice and _seed_voice_register; and an InputInterruptWatcher holding _watch_input_activity, _interrupt_for_listener and _resume_if_armed. Inject each into Daemon's constructor alongside the existing engine/sink/input_activity parameters so tests can substitute them. Keep the dispatch table and every wire response byte-identical. Then split clients/menubar/Sources/AITTSMenuBar/Views.swift by surface into CurrentPlaybackView.swift, QueueView.swift, HistoryView.swift and SettingsView.swift, moving views without editing their bodies. Re-run `uv run pytest`, `uv run ruff check`, `uv run mypy` and `swift test --package-path clients/menubar`; all must stay green.
```

### ⚠️ Cloud-Native - 12-Factor Compliance (Score: `3.00 / 5.0`)
```
Document the deliberate deviation from 12-factor logs in docs/design/architecture.md's bounded-diagnostics subsection: state that stdout is not used as the log stream because launchd would route it to an unbounded file, and that the bounded 0600 rotating file is the intended sink. Then confirm the already-supported foreground path (`ai-tts daemon` with no --log-file, which logs to the terminal) is mentioned in README next to the --log-file instructions so a developer knows both modes exist.
```

### ⚠️ Accessibility (UI) - WCAG Compliance (Score: `3.00 / 5.0`)
```
In clients/menubar/Sources/AITTSMenuBar/Views.swift, add explicit accessibility to every icon-only control in CurrentPlaybackCard: give each Button an .accessibilityLabel matching its .help text (Restart, Skip, Previous chunk, Next chunk, Full text, captions toggle), and give the ProgressView an .accessibilityValue describing elapsed and total time in spoken form. Add .accessibilityLabel to the chunk-progress capsules' container describing the chunk position, and mark the decorative capsules .accessibilityHidden(true). Add a test in clients/menubar/Tests/AITTSMenuBarTests/ asserting the accessibility label strings are non-empty for each transport action, then run `swift test --package-path clients/menubar`.
```

### ⚠️ Accessibility (UI) - Keyboard Navigability (Score: `3.00 / 5.0`)
```
Add .keyboardShortcut modifiers to the transport controls in CurrentPlaybackCard in clients/menubar/Sources/AITTSMenuBar/Views.swift: space for pause/resume, right/left arrow for next/previous chunk, and cmd-return for Skip. Give the Full text button cmd-shift-T. Confirm each shortcut is only active while the popover is key so it cannot fire from the captions panel. Do not add a global system hotkey in this change; note it as a follow-up because it needs an event tap and a separate Accessibility permission. Run `swift test --package-path clients/menubar`.
```

### ⚠️ Accessibility (UI) - Screen Reader Friendliness (Score: `3.00 / 5.0`)
```
In clients/menubar/Sources/AITTSMenuBar/Views.swift, make the InterruptionNotice announce itself: add .accessibilityElement(children: .combine) plus an .accessibilityLabel that reads the full reason sentence, and post an NSAccessibility announcement when state.interruption transitions from nil to non-nil. Do the same for the chunk counter so a change of chunk is announced. Leave the captions panel silent to VoiceOver, since it duplicates audio the user is already hearing, and add a comment saying so. Run `swift test --package-path clients/menubar`.
```

### ⚠️ Code Maturity - Versioning (Score: `3.00 / 5.0`)
```
Add a `--version` flag to the ai-tts CLI in src/aitts/cli.py that prints the installed distribution version via importlib.metadata plus the git commit it was built from if available, and cover it with a test asserting the flag exits 0 and prints the pyproject version. Do not create the git tag from an automated session: leave a note in CHANGELOG.md's Unreleased section stating that v0.1.0 must be tagged by the maintainer at the release commit, since tagging is a publishing decision.
```

### ⚠️ Code Maturity - Automated Deployment (Score: `3.00 / 5.0`)
```
Add a release job to .github/workflows/ci.yml that triggers on a pushed tag matching v*, runs the existing test suites, builds the wheel with `uv build`, runs scripts/build_app_bundle.py, and uploads both plus the supply-chain evidence directory as release assets. Keep the token read-only for the test jobs and grant contents:write only to the release job. Pin every action by commit SHA, matching the hardening already applied to the existing jobs. Do not enable any step that publishes to PyPI.
```