# AI-TTS

A local text-to-speech application for macOS, built for agents that talk.

You send it text. It queues that text, synthesizes audio in the background with the model held warm in memory, and plays it back through a separate, strictly serialized queue that you control from the menu bar.

> **Status: v0.1.0 — working.** The daemon, CLI, and menu-bar app are implemented and tested against the design under [`docs/design/`](docs/design/). See [Project status](#project-status) and [Using it](#using-it).

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
- **Shows you both queues** — what is still being generated, and what is ready and waiting.
- **Keeps everything ever said**, browsable and replayable.
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

```sh
# install (Python 3.12+, uv)
uv sync --all-extras

# run the daemon (holds Kokoro-82M warm, owns the audio device)
uv run ai-tts daemon

# speak — exit 0 means "accepted onto the queue", nothing more
uv run ai-tts say "Hello from an agent."

# speak and know it was actually heard — exit 0 only for Played
uv run ai-tts say "Deploy finished." --wait

# transport and visibility
uv run ai-tts pause | resume | skip | rewind
uv run ai-tts list playback
uv run ai-tts history
uv run ai-tts settings --set voice=bm_daniel
```

Every response is JSON. Agents that want more than the CLI speak newline-delimited JSON directly to the Unix socket at `~/Library/Application Support/ai-tts/ai-tts.sock` — the protocol is in [`docs/design/architecture.md`](docs/design/architecture.md) §5, and the CLI is only a convenience over it.

Text is **confidential by default**: an utterance submitted without an explicit `--sensitivity public` can never be routed to a non-local engine. There is no non-local engine wired in; that is a feature.

**Menu-bar app** (Swift):

```sh
cd clients/menubar && swift run
```

**Run the daemon at login** (launchd):

```sh
cp scripts/launchd/com.flyingrobots.ai-tts.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.flyingrobots.ai-tts.plist
```

## Project status

v0.1.0. The daemon (Python 3.12, asyncio), the CLI client, the Kokoro-82M engine adapter, and a Swift menu-bar app are implemented, with the test suite encoding the design semantics: the state machine, strict serial in-order playback, fail-closed sensitivity, restart recovery, and truthful exit codes. The design documents remain the spec; where v1 diverges (utterance-level rather than within-utterance rewind, stock SwiftUI controls rather than the pixel mockups), the divergence is deliberate and noted in the code.

## Licence

Apache License 2.0. Copyright 2026 James Ross. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
