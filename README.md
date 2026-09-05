# AI-TTS

A local text-to-speech application for macOS, built for agents that talk.

You send it text. It queues that text, synthesizes audio in the background with the model held warm in memory, and plays it back through a separate, strictly serialized queue that you control from the menu bar.

> **Status: v0.1.0 release candidate.** The daemon, CLI, MCP server, and menu-bar app are implemented and under release validation. No `v0.1.0` tag or release has been published yet. See [Project status](#project-status) and [Using it](#using-it).

## Why

Driving a TTS engine from shell scripts breaks in ways that are hard to see, because the failures are silent. Every one of these was observed in a single evening against a bare Kokoro install:

| Failure | What it looked like |
|---|---|
| The engine's server accepted text, queued it, and never played it | exit code 0, no audio, no error |
| The one-off wrapper discarded stderr — including the only line that reports playback | exit code 0, no audio, no error |
| A shell timeout killed the process mid-playback | audio truncated mid-sentence |
| Two utterances were submitted close together and played simultaneously | both voices at once, unintelligible |

None of these produced a nonzero exit code. A caller had no way to distinguish "spoke successfully" from "said nothing at all."

The last one is the clearest statement of the problem: **speech is a serial resource and nothing was serializing it.** That is a queue, and a queue needs an owner.

## What it does

- **Accepts text from any client** — an agent, a script, or you.
- **Treats any long input as one queue item with an internal clip queue**, so
  its first segment can play while later segments are still being synthesized
  and nothing submitted afterward can cut through it.
- **Distinguishes literal speech from Markdown.** Maintained agent and CLI
  speech defaults to `plain_text`; those clients parse Markdown only when the
  caller or file type marks it as `markdown`. Its syntax tree removes markup,
  preserves human labels and code content, and turns headings into spoken
  section cues without changing the stored source.
- **Enqueues text and documents from the menu bar.** Queue's **Read…** menu can
  acquire one current Accessibility selection, read explicitly copied text
  without changing the clipboard, or choose a file. Its file picker accepts
  UTF-8 plain text, Markdown, and PDFs with an extractable text layer. File
  paths stay in the app; only the selected document's text and interpretation
  are submitted.
- **Reads native macOS selections through Services.** Use **Read Selection with
  AI-TTS** on selected text or **Read File with AI-TTS** on one supported Finder
  file; both enter the same confidential, Normal-priority queue as the app and
  agent clients.
- **Exports six App Intents** for Read Text, Read File, Pause, Resume, Skip, and
  Set Playback Speed. They reuse the same application boundaries and appear in
  the action library when building a custom Shortcut. The bundle also emits
  `AppShortcutsProvider` metadata, but macOS does not expose that metadata as
  preconfigured App Shortcuts.
- **Synthesizes ahead of playback.** Generation is slow and parallelizable; playback is sequential and real-time. They are separate queues on purpose.
- **Caches generated audio**, so replaying costs nothing and a backed-up queue drains at playback speed rather than synthesis speed.
- **Plays one thing at a time**, in order, with an always-available global pause that lets incoming speech queue silently until you resume.
- **Shows one playback plan** — the current clip, everything upcoming in Queue, and removable local History.
- **Keeps local playback history** until you remove an item or clear it, with one-click priority-aware re-queue.
- **Lives in the menu bar.** Click the tray icon for the current state; the icon itself tells you at a glance whether it is idle, synthesizing, playing, or paused.
- **Changes playback rate live** at 0.5×, 0.75×, 1×, 1.5×, 2×, or 3× without
  restarting the current clip.
- **Shows opt-in on-screen captions** for the active spoken segment in a
  click-through panel that does not steal focus.
- **Configurable in the app** — voice and voice-generation speed — not as shell flags.

## Design documents

Read these in order. They are the current deliverable.

| Document | What it covers |
|---|---|
| [`docs/design/README.md`](docs/design/README.md) | Index, scope, and the questions still open |
| [`docs/design/features.md`](docs/design/features.md) | Feature breakdown, separated into stated, inferred, and proposed |
| [`docs/design/architecture.md`](docs/design/architecture.md) | Components, the two queues, utterance lifecycle, IPC, persistence |
| [`docs/design/engine-evaluation.md`](docs/design/engine-evaluation.md) | Whether Kokoro-82M is still the right engine; local and cloud alternatives |
| [`docs/design/tech-stack.md`](docs/design/tech-stack.md) | Language and framework choices, with the rejected options and why |
| [`docs/design/ui-design.md`](docs/design/ui-design.md) | Interaction design, with SVG mockups in [`mockups/`](docs/design/mockups/) |

## A note on what this speaks

This tool speaks whatever its callers hand it, which in practice includes **material its user is obliged to keep confidential** — personal names and internal identifiers among them. **Treat the text as sensitive by default.** Two consequences run through the design:

1. **Local inference is the default**, and any path that sends text off-machine is called out explicitly rather than assumed acceptable.
2. **The history store is local and never committed.** Runtime state, cached audio and the history database are all gitignored.

There is a third consequence that is not a software problem: **audio played during a live call is recorded into someone else's transcript**, where it is indistinguishable from a participant speaking. The application cannot know a call is in progress, so the calling agent has to.

These are stated at this level on purpose. **This repository is public**, so the design constraints belong here and the specifics of what has passed through the tool do not.

## Using it

Install the Python tools from a source checkout. Kokoro stays an optional,
locally resolved dependency so this repository never vendors or redistributes
its Python environment:

```sh
# requirements: macOS 14+, Python 3.12+, uv, Swift 5.10+, codesign
uv tool install --force --python 3.12 --with "kokoro>=0.9.4" .

# build an ad-hoc-signed, checkout-independent menu-bar app
python3 scripts/build_app_bundle.py \
  --output "$HOME/Applications/AI-TTS.app" \
  --force

# install and start a shell-free per-user launch agent
AI_TTS_BIN="$(uv tool dir --bin)/ai-tts"
python3 scripts/render_launch_agent.py \
  --executable "$AI_TTS_BIN" \
  --force
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.flyingrobots.ai-tts.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.flyingrobots.ai-tts.plist"
open "$HOME/Applications/AI-TTS.app"
```

### Install for coding agents

AI-TTS supports two local agent integrations. Use the CLI for any agent that
can run shell commands. Add the MCP adapter when the host supports local stdio
MCP servers and you want typed speech, status, queue, history, and transport
tools. Both integrations talk to the same daemon and serialized playback
queue; neither starts a second model or audio player.

The agent must run on the same Mac as AI-TTS and be allowed to execute the
installed binary and connect to the user-only Unix socket. A cloud-only agent
cannot reach a daemon on your laptop.

#### 1. Resolve and verify the installed commands

After completing the installation above, print the uv tool binary directory:

```sh
uv tool dir --bin
```

Use the absolute paths from that directory in agent instructions. This is more
reliable than assuming that a non-login agent shell inherited your interactive
`PATH`. Verify the daemon before configuring an agent:

```sh
AI_TTS_BIN="$(uv tool dir --bin)/ai-tts"

"$AI_TTS_BIN" status
"$AI_TTS_BIN" voices
"$AI_TTS_BIN" say "AI-TTS agent setup is connected." \
  --source setup-check
```

For checkout-only development, run `uv sync --all-extras` and substitute
absolute paths such as `/path/to/ai-tts/.venv/bin/ai-tts` and
`/path/to/ai-tts/.venv/bin/ai-tts-mcp`. Those paths follow that checkout and
virtual environment, so prefer the uv tool installation for durable,
machine-wide agent instructions.

The final command prints a JSON receipt. `"accepted": true` means the daemon
owns the utterance and has placed it in the plan; it does not mean playback has
already finished. If `status` reports `"playback_held": true`, the check is
still accepted and remains silent until the user resumes playback. Do not make
an installer or an agent release that hold automatically.

#### 2. Give any shell-capable agent a speech policy

Put a short policy in the agent's persistent system/developer instructions or
repository instruction file. Replace the example executable and voice with
absolute values reported by the commands above. Omit `--voice` if every agent
should use the current daemon default.

```md
## Spoken updates

- Use only `/Users/alex/.local/bin/ai-tts` for speech. Do not fall back to the
  macOS `say` command, `afplay`, a one-off TTS process, or another audio player.
- When the user asks you to speak, enqueue one concise, literal summary with:
  `/Users/alex/.local/bin/ai-tts say "<summary>" --source codex --voice bm_george`
- Pass generated prose as one shell argument. Speech is literal plain text by
  default; add `--format markdown` only when Markdown projection is intended.
- Treat exit code 0 and `"accepted": true` as queue admission, not proof that
  the utterance finished. Use `--wait` only when the task truly requires a
  Played outcome; it can remain blocked while global playback is paused.
- Continue submitting requested speech while playback is paused. The daemon
  safely synthesizes and spools it. Never resume, skip, cancel, or clear the
  user's playback unless the user asks.
- Omit `--sensitivity` or use `--sensitivity confidential` unless the user has
  affirmatively classified the text less restrictively.
- Do not speak when the user says they are in a call, meeting, recording, or
  other situation where audible output would be disruptive.
```

Use a stable `--source` value such as `codex`, `claude-code`, or
`release-bot`. It appears in Queue and History provenance. A stable `--voice`
also gives one agent a consistent audible identity; `ai-tts voices` lists the
valid ids on the installed engine.

For Codex, append the policy instead of overwriting existing instructions:

- `~/.codex/AGENTS.md` applies it across repositories;
- a repository-root `AGENTS.md` applies it to that project; and
- a more deeply nested `AGENTS.md` can specialize it for one subtree.

Codex reads its instruction chain when a session starts, so start a new
session after editing the file. The
[official Codex `AGENTS.md` guide](https://developers.openai.com/codex/guides/agents-md)
documents discovery and precedence. You can check what loaded before asking
for audio:

```sh
codex --ask-for-approval never "Summarize the active spoken-update instructions."
```

Then ask the agent, for example, “Use AI-TTS to say that the build passed.” A
correct CLI invocation returns an admission receipt immediately and lets the
daemon finish synthesis and playback independently of the agent process.

#### 3. Optionally give Codex typed MCP tools

The CLI policy is sufficient for speech. MCP is the richer option when the
agent should also inspect status, list Queue or History, discover voices, or
control playback with explicit typed tools. Register the installed local stdio
server with Codex:

```sh
codex mcp add ai-tts -- "$(uv tool dir --bin)/ai-tts-mcp"
codex mcp list
```

Start a new Codex session, then use `/mcp` to confirm that `ai-tts` is active.
Codex's desktop app, CLI, and IDE extension share this local MCP configuration.
The [official Codex MCP guide](https://developers.openai.com/codex/mcp)
documents the same `codex mcp add <name> -- <stdio-command>` form.

The server exposes these tools:

- `enqueue_speech`
- `speech_status`
- `list_speech_queue`
- `list_speech_history`
- `list_speech_voices`
- `get_caption_settings` and `set_captions_enabled`
- `pause_speech_playback` and `resume_speech_playback`
- `skip_current_speech` and `restart_current_speech`
- `cancel_queued_speech`, `requeue_speech`, and `clear_speech_queue`

Ask Codex to “use the AI-TTS `enqueue_speech` tool” if tool choice is
ambiguous. The MCP server's own instructions tell the agent that a global hold
does not reject new speech. Keep the behavioral rules from step 2 as well: MCP
provides capability and schemas, while the instruction file says when the
agent should use them and which user-owned transport actions require a request.

For another MCP-capable agent host, configure a local stdio server whose
command is the absolute path to `ai-tts-mcp`, with no arguments. Host-specific
configuration formats differ, but the process contract does not: stdout is MCP
JSON-RPC only, and the adapter connects to the already-running local daemon.

The installed app bundle contains only the native menu executable and its
metadata. It does not contain the Python environment, model, or voice assets.
Its ad-hoc signature is suitable for this local source-install workflow; it is
not a notarized package for third-party distribution.

To read highlighted text, select it in a macOS application and choose
**Application menu → Services → Read Selection with AI-TTS**. TextEdit is a
verified host. Some applications also place applicable Services in their
right-click menu; that placement belongs to the host application and is not
guaranteed. To read a document, select one supported plain-text, Markdown, or
text-bearing PDF file in Finder and choose **Finder → Services → Read File with
AI-TTS**. macOS can assign a keyboard shortcut to either command in System
Settings → Keyboard → Keyboard Shortcuts → Services.

For a host whose selection does not reach Services, open the AI-TTS popover
while that host is still frontmost, then choose **Queue → Read… → Read
Current Selection…**. This is an explicit Accessibility fallback: macOS may ask
for permission, and custom renderers may not expose selected text even after a
grant. Choose **Read Clipboard** only after copying text yourself; AI-TTS reads
the current string without issuing ⌘C or changing the clipboard. **Read File…**
opens the existing text/Markdown/PDF picker.

For automation, create a shortcut in Apple Shortcuts and search its action
library for **AI-TTS**. The installed app contributes **Read Text**, **Read
File**, **Pause**, **Resume**, **Skip**, and **Set Playback Speed**. Saving a
user shortcut around one of those actions also gives `/usr/bin/shortcuts run`
a shortcut name or identifier it can address; that command does not run a raw
App Intent type name directly.

On-screen captions are off by default. Open the AI-TTS menu-bar popover, choose
the gear icon, and enable **On-screen captions**. While a clip is actively
playing, the Current card also shows a captions-bubble shortcut beside playback
speed. The click-through panel appears at the bottom center of the active
display and shows one short phrase from the exact active segment; it never puts
an entire Markdown section or document segment on screen at once. Cues prefer
sentence and clause punctuation, are capped at 12 words and 84 characters, and
render in at most two lines. They advance from the reported clip position and
duration using the observed playback rate. That is smooth phrase-level timing,
not word-timed karaoke, so boundaries are intentionally approximate. Multi-part
documents also show `PART n OF m`, and the panel is absent while no segment is
active. A subdued label above the phrase shows the same exact source recorded in
History—for example, `codex:` or `menubar-file:notes.md:`—and is omitted only
for legacy items without source provenance. The preference is shared through
the daemon: the menu toggle and MCP `set_captions_enabled` tool update the same
persisted value, while `get_caption_settings` reports it without opening the
menu.

Use the installed CLI from the uv tool bin directory (or run
`uv tool update-shell` once to put that directory on `PATH`):

```sh
# exit 0 means "accepted onto the queue", nothing more
ai-tts say "Hello from an agent."

# agent speech is literal by default; opt into Markdown projection explicitly
ai-tts say $'# Release notes\n\nEverything is **ready**.' --format markdown

# exit 0 only after the clip reaches Played
ai-tts say "Deploy finished." --wait

# transport and visibility
ai-tts pause
ai-tts resume
ai-tts skip
ai-tts rewind
ai-tts list playback
ai-tts history
ai-tts settings --set voice=bm_daniel
ai-tts settings --set captions_enabled=true

# agent-native MCP server: 100% JSONL, one JSON object per stdio line
ai-tts-mcp
```

For development from the checkout instead:

```sh
uv sync --all-extras

# run the daemon (holds Kokoro-82M warm, owns the audio device)
uv run ai-tts daemon

uv run ai-tts say "Hello from the checkout." --wait
uv run ai-tts-mcp

# development-only menu launch; the instance lock rejects duplicates
cd clients/menubar
swift run
```

In the menu-bar app, open **Queue → Read…** and choose **Read File…**. Source
text is submitted byte-for-byte together with an explicit interpretation: `.md` and
`.markdown` use Markdown projection, while other UTF-8 text files and PDF text
layers remain literal plain text. PDF pages are submitted in the order returned
by the native macOS text extractor. Password-locked PDFs are refused; image-only
PDFs need OCR first because AI-TTS does not perform OCR or promise PDF layout
reconstruction.

**Pause is a playback hold, never backpressure.** Speakers should continue to
submit normally while playback is paused; accepted speech is synthesized and
spooled in Queue until the user resumes. `status` reports the daemon itself as
`accepting` and reports `playback_state` separately so an agent does not mistake
temporary silence for refusal.

Every response is JSON. Agents that want more than the CLI speak newline-delimited JSON directly to the Unix socket at `~/Library/Application Support/ai-tts/ai-tts.sock` — the protocol is in [`docs/design/architecture.md`](docs/design/architecture.md) §5, and the CLI is only a convenience over it.

MCP hosts should launch `ai-tts-mcp` as a local stdio server. The process emits
only newline-delimited MCP JSON-RPC on stdout; there is no HTTP or SSE mode.
Its typed tools cover enqueue, status, the unified Queue and History, voices,
shared caption read/write, global pause/resume, skip/restart, cancel,
priority-aware requeue, and queue clear. `enqueue_speech` defaults to literal
`plain_text` and accepts
`content_format: "markdown"` when an agent intentionally sends Markdown. It
remains available while globally paused: new clips are accepted, synthesized,
and spooled until Resume.

Both external client boundaries use a hexagonal port-and-adapter design. The
Python agent boundary keeps MCP schemas separate from daemon NDJSON. The native
Swift boundary is compile-time separated into `AITTSApplication` (public
models, ports, and use cases), `AITTSMacAdapters` (PDFKit, selected-file access,
and Unix-socket translation), `AITTSMacEntryPoints` (native Services,
Accessibility, and clipboard translation), and `AITTSMenuBar` (AppKit/SwiftUI
presentation and composition).
The installed text and file Services call `SelectionEnqueueing` and
`DocumentEnqueueing` without importing the menu UI or rebuilding speech, file,
or socket policy. The Accessibility, clipboard, and App Intents adapters use
those same application boundaries. See
[`docs/design/architecture.md`](docs/design/architecture.md) §4.

Text is **confidential by default**: an utterance submitted without an explicit `--sensitivity public` can never be routed to a non-local engine. There is no non-local engine wired in; that is a feature.

## Project status

The v0.1.0 implementation is a release candidate, not a published release. The
Python daemon and CLI, 100% JSONL stdio MCP adapter, Kokoro-82M engine adapter,
native Swift menu-bar app, native selected-text/selected-file Services,
explicit Accessibility/clipboard fallbacks, and six installed-and-indexed App
Intents are implemented. The suite encodes the state machine and serialized
playback plan,
global hold, fail-closed sensitivity, restart recovery, bounded cache and
shutdown, single-instance menu process, public schemas, and
checkout-independent release artifacts. Representative Services-menu host
acceptance and the remaining release-readiness work and accepted blind spots
are tracked in
[`docs/standards/testing-profile.md`](docs/standards/testing-profile.md).

## Licence

Apache License 2.0. Copyright 2026 James Ross. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
