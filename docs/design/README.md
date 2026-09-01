# Design documents

Status: **implemented in v0.1.0**. These documents were the pre-implementation spec and remain the reference; open questions below are still open where unanswered. This file is the index: what each document covers, the order to read them in, and every question that is still open.

## Scope

AI-TTS is a local-first, single-user speech daemon for macOS. Agents and scripts submit text; the daemon synthesizes audio ahead of playback with the model held warm, plays exactly one utterance at a time, and gives the user transport control from a menu-bar app. The design exists because the shell-script setup it replaces failed four ways in one evening, three of them silently at exit 0. Those failures are catalogued at the top of [`architecture.md`](architecture.md) and drive everything else.

Out of scope for v1: multiple users, multiple machines, any network transport, and any cloud engine. The last is a confidentiality decision, not a deferral (see [`engine-evaluation.md`](engine-evaluation.md) §1).

## Reading order

| Document | What it covers | Depends on |
|---|---|---|
| [`features.md`](features.md) | What the thing does. Every feature labelled STATED / INFERRED / PROPOSED with priority, so proposals can be cut in one pass | — |
| [`architecture.md`](architecture.md) | The two queues, the utterance lifecycle, components, IPC, persistence, transport semantics, sensitivity routing | features |
| [`engine-evaluation.md`](engine-evaluation.md) | Whether Kokoro-82M is still the right engine. Answer: yes, and why the cloud field is disqualified | — |
| [`tech-stack.md`](tech-stack.md) | Language and framework choices, with the rejected options and why | architecture, engine-evaluation |
| [`ui-design.md`](ui-design.md) | Interaction design for the menu-bar app, with mockups in [`mockups/`](mockups/) | features, architecture |

`features.md` separates *what* from *how* and is the document to argue with first. If a feature falls out of it, the sections built on that feature fall with it.

## Open questions

Every unresolved question across the set, in one list. The detail and the reasoning live at the linked sections; this is only the ledger.

**Transport semantics** — the two most important, because they are the controls that get pressed most:

1. What does **skip** actually do — abandon the current utterance, or drop the next one unheard? ([features §Open questions #1](features.md#open-questions))
2. What does **rewind** actually do — back N seconds within the current utterance (and what is N?), or replay the previous one? ([features #2](features.md#open-questions), [architecture §10.1](architecture.md#10-open-questions-for-review))

**History:**

3. "It should all be there" — permanent, with no automatic expiry? ([features #3](features.md#open-questions), [architecture §10.4](architecture.md#10-open-questions-for-review))
4. Searchable and replayable, or only a record? ([features #4](features.md#open-questions))
5. Where does history live and does it need protection beyond file permissions, given the text is client-confidential? ([features #5](features.md#open-questions))

**Synthesis:**

6. Confirm synthesis stays entirely on-machine, or name the exception explicitly. ([features #6](features.md#open-questions))
7. Confirm "cached and ready" means synthesize *ahead of* playback. Most of the queue design rests on this reading. ([features #7](features.md#open-questions))
8. On a voice change, what happens to audio already rendered in the old voice? ([features #8](features.md#open-questions))

**Ordering and scope:**

9. Is playback order strictly submission order, even when a short item synthesizes first? ([features #9](features.md#open-questions))
10. Are the input-queue and playback-queue views actually distinct in the UI, or one list with per-item state? ([features #10](features.md#open-questions))
11. Is the full MUST set the v1, or should a smaller first cut be proposed as a separate document? ([features #11](features.md#open-questions))

**Architecture:**

12. Is within-utterance seeking required for v1, or is utterance-level rewind enough? ([architecture §10.1](architecture.md#10-open-questions-for-review))
13. Are two priority levels (`normal`/`urgent`) sufficient, and is barge-in correctly off by default? ([architecture §10.2](architecture.md#10-open-questions-for-review))
14. One output device, or is routing a setting the playback controller owns? ([architecture §10.3](architecture.md#10-open-questions-for-review))
15. Should the daemon *refuse* text that looks confidential but was declared `public`, or is fail-closed defaulting enough? Deliberately unresolved. ([architecture §10.5](architecture.md#10-open-questions-for-review))
16. Should history record which client submitted each utterance? ([architecture §10.6](architecture.md#10-open-questions-for-review))

**Engine** — none open. The evaluation closed with a recommendation (keep Kokoro-82M, local only) and a list of conditions that would reopen it ([engine-evaluation §5](engine-evaluation.md#5-what-would-change-this-answer)).

## What approval means

Approving these documents authorizes implementation of the MUST set in [`features.md`](features.md) against the architecture as written. It does not settle the open questions above — any that remain unanswered at approval time get resolved as they are hit, and the resolution recorded back into the relevant document. The documents stay the spec until tests exist to take over that job.
