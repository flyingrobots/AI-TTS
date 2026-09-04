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
- **Synthesizes ahead of playback.** Generation is slow and parallelizable; playback is sequential and real-time. They are separate queues on purpose.
- **Caches generated audio**, so replaying costs nothing and a backed-up queue drains at playback speed rather than synthesis speed.
- **Plays one thing at a time**, in order, with an always-available global pause that lets incoming speech queue silently until you resume.
- **Shows one playback plan** — the current clip, everything upcoming in Queue, and removable local History.
- **Keeps local playback history** until you remove an item or clear it, with one-click priority-aware re-queue.
- **Lives in the menu bar.** Click the tray icon for the current state; the icon itself tells you at a glance whether it is idle, synthesizing, playing, or paused.
- **Configurable in the app** — voice, speed, output device — not as shell flags.

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

The installed app bundle contains only the native menu executable and its
metadata. It does not contain the Python environment, model, or voice assets.
Its ad-hoc signature is suitable for this local source-install workflow; it is
not a notarized package for third-party distribution.

Use the installed CLI from the uv tool bin directory (or run
`uv tool update-shell` once to put that directory on `PATH`):

```sh
# exit 0 means "accepted onto the queue", nothing more
ai-tts say "Hello from an agent."

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

**Pause is a playback hold, never backpressure.** Speakers should continue to
submit normally while playback is paused; accepted speech is synthesized and
spooled in Queue until the user resumes. `status` reports the daemon itself as
`accepting` and reports `playback_state` separately so an agent does not mistake
temporary silence for refusal.

Every response is JSON. Agents that want more than the CLI speak newline-delimited JSON directly to the Unix socket at `~/Library/Application Support/ai-tts/ai-tts.sock` — the protocol is in [`docs/design/architecture.md`](docs/design/architecture.md) §5, and the CLI is only a convenience over it.

MCP hosts should launch `ai-tts-mcp` as a local stdio server. The process emits
only newline-delimited MCP JSON-RPC on stdout; there is no HTTP or SSE mode.
Its typed tools cover enqueue, status, the unified Queue and History, voices,
global pause/resume, skip/restart, cancel, priority-aware requeue, and queue
clear. `enqueue_speech` remains available while globally paused: new clips are
accepted, synthesized, and spooled until Resume.

The MCP boundary uses a hexagonal port-and-adapter design. Public immutable
schemas and `SpeechServicePort` are transport-neutral; the MCP adapter owns MCP
tool encoding, and the Unix-socket adapter owns daemon NDJSON encoding. See
[`docs/design/architecture.md`](docs/design/architecture.md) §5.

Text is **confidential by default**: an utterance submitted without an explicit `--sensitivity public` can never be routed to a non-local engine. There is no non-local engine wired in; that is a feature.

## Project status

The v0.1.0 implementation is a release candidate, not a published release. The
Python daemon and CLI, 100% JSONL stdio MCP adapter, Kokoro-82M engine adapter,
and native Swift menu-bar app are implemented. The suite encodes the state
machine, serialized playback plan, global hold, fail-closed sensitivity,
restart recovery, bounded cache and shutdown, single-instance menu process,
public schemas, and checkout-independent release artifacts. The remaining
release-readiness work and accepted blind spots are tracked in
[`docs/standards/testing-profile.md`](docs/standards/testing-profile.md).

## Licence

Apache License 2.0. Copyright 2026 James Ross. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
