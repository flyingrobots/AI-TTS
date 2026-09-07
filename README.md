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
  are submitted. Text and Markdown are limited to 512 KiB. PDFs are limited to
  32 MiB, 500 pages, and 512 KiB of extracted text, so file acquisition is
  bounded before the daemon's 1 MiB request boundary.
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
- **Steps between the chunks of a long document** — next and previous chunk
  appear beside Skip when a submission was split, so you can move past a
  paragraph without abandoning the whole thing.
- **Reads any clip in full** in its own window, from the current clip or any
  History row. Captions show one chunk and the popover shows a few lines;
  this shows all of it, without writing your speech to a file.
- **Yields the floor when you start speaking.** Playback stops as soon as
  something starts using the microphone and waits for you, because dictating
  to an agent only works as a conversation if your own voice outranks the
  queue. Configurable, including whether it resumes by itself afterwards.
- **Gives every client its own voice.** The daemon keeps the register, so two
  agents cannot end up sharing a voice; you can see the mapping and override
  any of it, and your assignment outranks whatever the client asks for.
- **Follows your audio output.** Speech moves with the system default output
  device, mid-clip, instead of continuing to speakers you have left.
- **Configurable in the app** — voice and voice-generation speed — not as shell flags.

## Design documents

Read these in order. They are the current deliverable.

| Document | What it covers |
|---|---|
| [`docs/design/README.md`](docs/design/README.md) | Index, scope, and the questions still open |
| [`docs/design/features.md`](docs/design/features.md) | Feature breakdown, separated into stated, inferred, and proposed |
| [`docs/design/architecture.md`](docs/design/architecture.md) | Components, the two queues, utterance lifecycle, IPC, persistence |
| [`docs/design/one-utterance.md`](docs/design/one-utterance.md) | The life of one utterance in order, module by module. Start here to change code |
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

**macOS only.** AI-TTS owns a CoreAudio output device and installs a launchd
user agent, neither of which exists elsewhere; the Makefile refuses to run on
any other host rather than half-installing.

```sh
# requirements: macOS 14+, Python 3.12+, uv, Swift 5.10+, codesign
make                 # build the menu-bar app into dist/
make install         # install the CLI, MCP server, app, and launchd agent
make install-agents  # wire it into every local coding agent found
make doctor          # is the daemon up, and what is wired in?
make help            # every target
```

`make install-all` does all three. `make uninstall` stops and removes the
launchd agent and the executables, and deliberately leaves your speech history,
cached audio, and installed app alone.

Agent integrations take the agents by name, either through make or by calling
the installer directly:

```sh
make install-mcp                        # every agent found
make install-skill AGENTS="--claude"    # just one

./scripts/install-integration.sh mcp   --claude --codex
./scripts/install-integration.sh skill --all --dry-run
```

Supported: `--claude`, `--codex`, `--gemini`, `--all`. An agent whose CLI is
not installed is skipped rather than failing the run, and `--dry-run` prints
each host's own `mcp add` command so an unsupported agent can be wired up by
hand.

### Doing it by hand

The Makefile is a convenience over three steps you can run yourself. Kokoro
stays an optional, locally resolved dependency so this repository never vendors
or redistributes its Python environment:

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

### Local diagnostic log

The installed launch agent passes an explicit `--log-file` to the daemon. AI-TTS
keeps `~/Library/Logs/AI-TTS/daemon.log` plus two rotated backups, each capped at
2 MiB (about 6 MiB total). The directory is normalized to owner-only `0700` and
every log generation to `0600`; a symlink in place of the active log is refused.
An oversized generation left by an older installation is discarded when the
bounded handler starts, rather than surviving indefinitely as a large backup.

The file contains timestamps, severity, component names, stable operational
event codes, and a small allowlist of non-content values such as byte counts,
retry delays, the AI-TTS version, and engine name. Package diagnostics do not
include speech text, source labels, selected-document or cache paths, exception
messages, tracebacks, or stack payloads. Individual records are also truncated
before they can exceed half of one log generation. Launchd sends unrelated
stdout and stderr to `/dev/null` so they cannot bypass the bound.

Foreground development without `--log-file` still logs to the terminal. To use
the same policy manually, run `ai-tts daemon --log-file /absolute/path/to/log`.
To remove retained diagnostics, stop the launch agent, delete the three explicit
`daemon.log`, `daemon.log.1`, and `daemon.log.2` files, then bootstrap it again;
the daemon recreates the active file privately.

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

Replace `<AI_TTS_BIN>` below with the absolute path printed by
`uv tool dir --bin`; a non-login agent shell may not inherit your `PATH`.

```md
## Spoken updates

- Use only `<AI_TTS_BIN>` for speech. Do not fall back to the
  macOS `say` command, `afplay`, a one-off TTS process, or another audio player.
- When the user asks you to speak, enqueue one concise, literal summary with:
  `<AI_TTS_BIN> say "<summary>" --source codex`
- Always pass the same `--source`. It is the identity the daemon keys each
  client's voice on. `--voice` is only a first-time preference: once a source
  holds a voice, that voice wins over any later request, and a voice another
  source already holds is declined in favour of a free one.
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
`release-bot`. It appears in Queue and History provenance, and it is the
identity the voice register is keyed on.

`--voice` is now a preference rather than a decision. The first time a
`--source` speaks, the daemon records the voice it ends up with and keeps it
for that source from then on, so an agent sounds the same across sessions
without having to remember anything. A voice another source already holds is
declined in favour of a free one — that is the collision the register exists
to prevent. Assign or change any of it under **Agent voices** in Settings;
what you set there wins over `--voice`. `ai-tts voices` lists the valid ids on
the installed engine.

### The voice catalog, and adding to it

`ai-tts voices` reports 41 voices across six languages. That list is curated
rather than copied from the model repository: every entry was verified to
synthesize with the grapheme-to-phoneme dependencies this project installs.
The Japanese and Mandarin voices ship in the same model repository and are
deliberately absent, because they need `misaki[ja]` (which builds
`pyopenjtalk` from source and bundles Open JTalk) or `misaki[zh]` — a
supply-chain decision rather than a voice-list edit.

If you install those extras yourself, or a new upstream release adds a voice,
declare it and the daemon will offer it:

```sh
AI_TTS_EXTRA_VOICES=jf_alpha,zm_yunxi ai-ttsd
```

Declared names are validated for shape and de-duplicated against the curated
list; a malformed name is dropped rather than accepted, because a voice the
catalog offers but cannot speak fails at synthesis instead of at the point you
typed it. Whether the language backend is actually installed is yours to know
— the daemon takes the declaration at its word.

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

#### 3. Optionally install the bundled skill

[`skills/speak/SKILL.md`](skills/speak/SKILL.md) states the same policy as a
skill: which command to use, how to read `status` before speaking, what
`--source` and the voice register mean, and how to write text that is bearable
to listen to.

It follows the open agent-skills layout — one `SKILL.md` with `name` and
`description` frontmatter in a directory named after the skill — so the same
file works for Claude Code, Codex and Gemini:

```sh
make install-skill                      # every agent found
make install-skill AGENTS="--codex"     # just one
```

The installer replaces the committed `<AI_TTS_BIN>` placeholder with the
absolute path on this machine, so the copy an agent reads names a real
executable while the copy in the repository stays machine-independent. Set
`--source` in your copy to the name that agent should be known by. Skills are
discovered at session start, so start a new session afterwards.

The skill is a starting point rather than a policy: edit your copy freely.
Anything specific to you — how you like to be addressed, which meetings are
sensitive, when silence is preferred — belongs in your copy, not in the
repository's.

#### 4. Optionally give Codex typed MCP tools

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
- `speech_metrics`
- `list_speech_voices`
- `get_caption_settings` and `set_captions_enabled`
- `pause_speech_playback` and `resume_speech_playback`
- `skip_current_speech` and `restart_current_speech`
- `cancel_queued_speech`, `requeue_speech`, and `clear_speech_queue`
- `purge_cached_audio`

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

# block on one clip you already have the id of
ai-tts wait utt_1a2b3c4d

# transport
ai-tts pause
ai-tts resume
ai-tts skip
ai-tts rewind

# what the daemon is doing, and what it can speak
ai-tts status
ai-tts voices

# the queues: 'playback' is the speaking plan, 'input' is what is still
# being synthesized
ai-tts list playback
ai-tts list input
ai-tts history
ai-tts purge-cache

# give up on something before it is spoken, or drain a whole queue
ai-tts cancel utt_1a2b3c4d
ai-tts clear input

# how long synthesis and the playback queue are actually taking
ai-tts metrics

# within one chunked document, rather than abandoning the whole entry
ai-tts next-chunk
ai-tts prev-chunk

# release the hold once nothing is using the microphone
ai-tts resume-when-idle

# which voice each speaking client holds, and overriding it
ai-tts voice-map
ai-tts assign-voice claude-code af_heart
ai-tts assign-voice claude-code --release

ai-tts settings --set voice=bm_daniel
ai-tts settings --set captions_enabled=true
ai-tts settings --set input_interrupt_enabled=true
ai-tts settings --set input_interrupt_resume=manual

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

**Purge Cached Audio…** is also available in Settings, and `ai-tts
purge-cache` exposes the same operation to scripts. It removes reusable and
orphaned WAV files while retaining audio still owned by current or queued
speech, so it never interrupts playback. History text remains; rows whose
audio was removed are replayed by synthesizing again. The JSON receipt reports
removed, protected, and failed file counts and bytes.

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
priority-aware requeue, queue clear, and safe cached-audio purge.
`enqueue_speech` defaults to literal
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
Intents are implemented. Playback also follows the system default output
device, yields the floor when the microphone goes live, steps between the
chunks of one document, reads any clip in full in its own window, and keeps a
per-client voice register over a 41-voice, six-language catalog.

The suite encodes the state machine and serialized playback plan, global hold,
fail-closed sensitivity, restart recovery, bounded cache and shutdown,
single-instance menu process, public schemas, and checkout-independent release
artifacts. Representative Services-menu host
acceptance and the remaining release-readiness work and accepted blind spots
are tracked in
[`docs/standards/testing-profile.md`](docs/standards/testing-profile.md).

## Licence

Apache License 2.0. Copyright 2026 James Ross. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
