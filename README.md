# AI-TTS

A local text-to-speech application for macOS, built for agents that talk.

You send it text. It queues that text, synthesizes audio in the background with the model held warm in memory, and plays it back through a separate, strictly serialized queue that you control from the menu bar.

> **Status: design.** No implementation exists yet. The documents under [`docs/design/`](docs/design/) are under review and nothing has been built. See [Project status](#project-status).

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
- **Plays one thing at a time**, in order, with play, pause, skip and rewind.
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

## Project status

Design under review. Nothing is implemented, and no code should be written until the design documents are approved.

## Licence

Apache License 2.0. Copyright 2026 James Ross. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
