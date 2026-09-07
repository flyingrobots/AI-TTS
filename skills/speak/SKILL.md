---
name: speak
description: Speak text aloud through the AI-TTS daemon, which serializes every agent's speech so no two agents talk over each other. Use whenever the user asks for something to be read, said, or spoken aloud.
---

# speak

All speech goes through the **AI-TTS daemon**. It owns the audio device, queues
utterances so agents never overlap, records who said what, and honours a hold
when the user pauses it.

The commands below name the `ai-tts` executable by absolute path, because a
non-login agent shell may not inherit an interactive `PATH`. If a command
still shows a bracketed placeholder, this copy was not installed by
`make install-skill`; replace it with the output of `uv tool dir --bin`
suffixed with `/ai-tts`.

## Run it

```bash
<AI_TTS_BIN> say --source <your-agent-name> --wait --timeout 570 \
  "$(cat /path/to/speech.txt)"
```

Write the speech to a file first, even for one sentence. It keeps quoting out
of the way and leaves a re-playable record. Put it in the session scratchpad
rather than a shared temp directory. The text is a **positional argument**;
there is no `-f` flag.

Set the Bash tool's `timeout` to **600000**. Generation is roughly real-time,
so keep `--timeout` just under it. For anything longer than a few paragraphs,
run it in the background instead of waiting.

`--wait` is what makes the exit code mean something: **exit 0 only for
`Played`**. Without it, exit 0 means "accepted onto the queue", not "was
heard". The JSON receipt ends with `"final_state": "Played"` on success.

## Check the queue before speaking

```bash
<AI_TTS_BIN> status
```

- `"playback_held": true` — the user has held the queue, often for a meeting.
  **Say it in text instead.** Queued speech fires the moment they resume,
  which is exactly the wrong moment.
- `"interruption"` is non-null — playback stopped because the user started
  speaking. Do not resume it on their behalf.
- Exit code 2 — the daemon is down. **Report that; never fall back to another
  audio path.**

`submission_guidance` states the current disposition in words. Trust it.

## Voice

Pass `--source` with a stable name for your agent on every call. It is how
history attributes speech, and it is the identity the daemon keys each
client's voice on.

The daemon assigns the voice. The first time a source speaks, whatever voice
it ends up with is recorded and kept for that source from then on, so an agent
sounds the same across sessions without having to remember anything. A voice
another source already holds is declined in favour of a free one, so two
agents cannot end up sounding alike.

```bash
<AI_TTS_BIN> voice-map   # who holds which voice
<AI_TTS_BIN> voices      # the catalog this engine offers
```

`--voice` is therefore a first-time preference, not a decision: a voice
already held wins over a later request, and a voice the user assigned wins
over both. Do not reassign another client's voice; that is the user's call.

## Sensitivity

Omitting `--sensitivity` means **confidential**, which fails closed. That is
the right default. Pass `--sensitivity public` only when the text is genuinely
safe to paste into a public channel.

## Write for the ear, not the terminal

Markdown read aloud is unlistenable. Before speaking:

- Drop backticks, pipes, headers, table pipes, and emoji entirely.
- Spell identifiers as a person would say them: `verify.py` becomes "verify
  dot p y"; `*.txt` becomes "dot t x t"; `A256` becomes "A two five six".
- Turn tables into sentences, and bullet lists into short paragraphs.
- Expand numbers that carry meaning: `258` becomes "two hundred and
  fifty eight".
- Keep it short and load-bearing. One or two sentences beats a paragraph.

## When not to speak

**If a meeting is plausibly live, stay silent and say so in text instead.**
Anything spoken during a call lands in someone else's recording, including
recordings you cannot see and cannot retract. A general permission to speak
never overrides an unheard "I'm in a meeting".

Prefer text whenever the user has not asked to be spoken to, when the content
is long, or when it is something they will want to re-read rather than hear.

## Never bypass the daemon

No `afplay`, no `say`, no direct calls to the synthesis engine. Direct engine
calls bypass the daemon's serialization, which is the only thing stopping two
agents from talking over each other, and they will not honour a hold.
