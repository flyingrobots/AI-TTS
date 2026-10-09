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
<AI_TTS_BIN> say --source <your-agent-name> \
  "$(cat /path/to/speech.txt)"
```

Write the speech to a file first, even for one sentence. It keeps quoting out
of the way and leaves a re-playable record. Put it in the session scratchpad
rather than a shared temp directory. The text is a **positional argument**;
there is no `-f` flag.

Return after the daemon accepts the request into its queue. Do not add `--wait`
for ordinary agent speech, and do not poll until playback finishes inside the
submission tool call. Exit 0 means admission succeeded; it does not mean the
listener has heard the speech. An error means admission was not confirmed.

Keep the JSON receipt's `id` (for example `utt_...`). To check progress later,
make a separate, nonblocking call:

```bash
<AI_TTS_BIN> get <utterance-id>
```

If an older installed CLI does not yet support `get`, inspect `list input`,
`list playback`, and `history` for the receipt ID instead. Never resubmit the
same text merely to check progress.

Read `item.state`: `Queued`, `Synthesizing`, `Ready`, `Playing`, `Paused`,
`Played`, `Skipped`, `Cancelled`, or `Failed`. `Played` means playback completed;
`Ready` means audio is prepared. A global hold may leave a clip `Ready` while
waiting for Resume; use `status` to inspect that hold.

Only when the user explicitly needs confirmation of completed playback, use
`wait <utterance-id> --timeout 570` as a separate call. Exit 0 from `wait` means
`Played`; its receipt has `final_state`. A timeout does not cancel speech.

## Queue speech even while paused

Always enqueue speech the user requested. A playback hold controls when the
listener hears it; it does not close admission. Submit once through `say`,
including during dictation or a meeting hold. The daemon saves the speech for
playback when the hold is released, so the listener can hear it and respond
later.

`status` is optional diagnostic information, never a prerequisite for enqueueing:

```bash
<AI_TTS_BIN> status
```

- `"playback_held": true`: enqueue normally. Report "Queued for playback when the pause ends."
- `"interruption"` is non-null: enqueue normally. Microphone pauses resume
  automatically when no input is active under the default `when_idle` policy.
  Leave playback controls to the listener and daemon.
- A manual pause waits for the listener to resume. Keep requested speech queued.
- Exit code 2 with an unavailable daemon: report the connection failure.
  Use the daemon as the only audio path.

A wait timeout does not cancel an accepted submission. Keep its utterance ID
and check that entry later instead of submitting a duplicate. Say "queued"
while it is pending; claim playback only after `final_state: Played`.
`submission_guidance` describes admission separately from playback.

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

## When to use text

Use text when the user has not requested speech or explicitly asks for text.
When speech is requested during a pause, queue it and let the daemon manage
playback. Respect an explicit request for silence and leave an active hold in
place.

## Never bypass the daemon

No `afplay`, no `say`, no direct calls to the synthesis engine. Direct engine
calls bypass the daemon's serialization, which is the only thing stopping two
agents from talking over each other, and they will not honour a hold.
