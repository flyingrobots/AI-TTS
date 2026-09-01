# TTS engine evaluation

**Question:** Is Kokoro-82M still the right engine for this application, or is there a better local model or a cheap-enough cloud service?

**Answer: Yes — keep Kokoro-82M.** Not because it is the best-sounding engine available, but because it is the only candidate that clears all three hard constraints at once: it is Apache 2.0, it never sends text off the machine, and it is fast enough on Apple Silicon that latency is not the limiting factor. Every engine that beats it on quality fails at least one of those, and the failures are not close.

Researched 2026-08-28. Every claim below carries a source. Claims I could not verify against a primary source are typed `unverified` rather than stated.

---

## 1. The constraint that decides this

This tool speaks material its user is obliged to keep confidential — personal names and internal identifiers among them.

**Sending that text to a cloud TTS API is disclosing client-confidential material to a third party.** Not "potentially": the text is the request body. Every cloud option below is evaluated on that basis first and on price second, because at the volumes involved the price differences are trivial and the disclosure is not.

Two findings make this decisive rather than cautionary:

- **ElevenLabs Zero Retention Mode is Enterprise-only.** On the Free, Starter, Creator, Pro, and Scale tiers, submitted audio may be used to improve ElevenLabs' models unless the user actively opts out, and the opt-out applies prospectively only, so material already submitted may already be in a training set. ([ElevenLabs Zero Retention Mode docs](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode))
- **OpenAI does not train on API data by default, but retains inputs for up to 30 days** for abuse monitoring. Zero Data Retention requires prior approval on an enterprise agreement and is not available on pay-as-you-go. ([OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data))

So the affordable tier of the best-sounding provider is the one that may train on the text, and the cheapest credible provider still parks it on someone else's disk for a month.

**Rule this implies, if any cloud engine is ever wired in:** cloud TTS may speak only text that would be safe to paste into a public channel: release notes, public documentation, generic UI strings. It may never speak working-repository content, internal notes and analysis, artifact content, or anything naming a colleague, a customer, an internal identifier, or an access list. That boundary has to be enforced in code, not in a habit, because the failure is silent and irreversible.

---

## 2. Local models

| Engine | Params | Licence | Apple Silicon | Streaming | Verdict |
|---|---|---|---|---|---|
| **Kokoro-82M** | 82M | **Apache 2.0** ([HF card](https://huggingface.co/hexgrad/Kokoro-82M)) | Native MLX + CoreML ports ([kokoro-mlx](https://github.com/gabrimatic/kokoro-mlx), [kokoro-coreml](https://huggingface.co/mattmireles/kokoro-coreml)) | Chunked ([streaming-tts](https://github.com/nikkoxgonzales/streaming-tts)) | **Keep** |
| **Chatterbox** (Turbo/Nano) | 350M / 110M | **MIT** ([GitHub](https://github.com/resemble-ai/chatterbox)) | `mps` device in examples | `unverified` | Strongest challenger |
| **Orpheus** | 3B | Apache 2.0 ([Modal survey](https://modal.com/blog/open-source-tts)) | `unverified` | `unverified` | Too large for this job |
| **Sesame CSM-1B** | 1B | Apache 2.0 ([Modal survey](https://modal.com/blog/open-source-tts)) | `unverified` | `unverified` | Conversational, not narration |
| **Piper** | small | **GPL-3.0** ([GitHub](https://github.com/OHF-Voice/piper1-gpl)) | `unverified` | `unverified` | ⚠ licence conflict — see below |
| **F5-TTS** | — | code MIT, **weights CC-BY-NC-4.0** ([HF](https://huggingface.co/SWivid/F5-TTS)) | — | — | **Disqualified** |
| **XTTS-v2 / Coqui** | — | **Coqui Public Model License, non-commercial** ([discussion](https://github.com/coqui-ai/TTS/discussions/4304)) | — | — | **Disqualified** |

### ⚠ Two licence problems worth flagging before anyone prototypes

This repo is Apache 2.0 and headed for a public remote at `flyingrobots/AI-TTS`, so licence contamination is a real constraint rather than a formality.

- **Piper is GPL-3.0.** Shelling out to a separate `piper` binary is normally mere aggregation and does not force the calling project to GPL. Linking it as a library, vendoring its code, or distributing it inside an app bundle plausibly does. If Piper is ever considered, that call needs making deliberately and probably needs a lawyer's read, not mine. I am flagging it, not resolving it.
- **F5-TTS and XTTS-v2 are both non-commercial on the weights**, even though both ship MIT code. XTTS-v2 is worse than non-commercial: Coqui shut down in January 2024, so there is no longer anyone who *can* sell a commercial licence. Neither belongs in an Apache-2.0 public repo. Rule them out now rather than after someone builds against them.

### Why Kokoro survives the comparison

- **Fast enough that latency stops mattering.** Reported ~0.1× real-time factor on an M3 Max — roughly one minute of audio in six seconds — and ~14× faster than realtime on an M1 Mini (`unverified`, secondary sources: [Contra Collective](https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026), [RunAnywhere](https://www.runanywhere.ai/blog/metalrt-speech-fastest-stt-tts-apple-silicon)). Even if those figures are optimistic by 3×, a multi-paragraph report still synthesises faster than it plays. **Throughput is not the bottleneck for this application; it is already solved.**
- **It handles long text without aggressive chunking**, which matters specifically for the multi-paragraph technical prose this tool reads (`unverified`, secondary source: [Kokoro Web](https://kokoroweb.app/en/blog/kokoro-tts-lightweight-browser-text-to-speech)). Models that require splitting into short segments and then post-processing out the seams are a worse fit for long documents regardless of their per-sentence quality.
- **8 languages, 54 voices at v1.0**, so "configurable voice" is satisfiable without a second engine ([HF card](https://huggingface.co/hexgrad/Kokoro-82M)).
- **Apache 2.0** — no friction with the repo licence, no attribution complexity, no commercial ambiguity.

### The strongest challenger, honestly stated

**Chatterbox Turbo (350M, MIT)** is the one that could displace Kokoro. Resemble's own blind listening study reports 65.3% preference for Chatterbox over ElevenLabs against 24.5% the other way ([Resemble](https://www.resemble.ai/learn/models/chatterbox-turbo)). That is a vendor's self-report on its own model and should be read as marketing, not as an independent benchmark. Even so, the model is MIT-licensed, 4× Kokoro's size (still small), and its code examples list `mps`, implying Apple Silicon support.

**If quality on long technical prose turns out to be the real complaint, Chatterbox is the first thing to A/B, not a cloud service.** It keeps every property that makes Kokoro acceptable and may beat it on naturalness.

---

## 3. Cloud services

Pricing verified against vendor pages where possible.

| Service | Price | Source | Confidentiality posture |
|---|---|---|---|
| **OpenAI `tts-1`** | **$15 / 1M chars** | [pricing](https://developers.openai.com/api/docs/pricing) | No training by default; **30-day retention**; ZDR enterprise-only |
| **OpenAI `tts-1-hd`** | **$30 / 1M chars** | [pricing](https://developers.openai.com/api/docs/pricing) | as above |
| **Deepgram Aura-2** | ~$30 / 1M chars | `unverified` — secondary only ([TextToLab](https://texttolab.com/blog/deepgram-pricing)) | `unverified` |
| **Cartesia Sonic** | Pro $5/100K, Startup $49/1.25M, Scale $299/8M credits | [pricing](https://cartesia.ai/pricing) | `unverified` |
| **ElevenLabs** | Creator $22/121K, Pro $99/600K, Scale $299/1.8M, Business $990/6M credits | [pricing](https://elevenlabs.io/pricing) | **May train on input below Enterprise**; ZRM Enterprise-only |

**Derived per-million rates**, arithmetic mine from the credit figures above: ElevenLabs runs **≈$165–182 per million characters** across every tier; the credit-to-character mapping is 1:1 for V2 multilingual models per their pricing page. Cartesia works out to **≈$37–50 per million credits**; I am treating credits as characters on a secondary source ([TextToLab](https://texttolab.com/blog/cartesia-pricing)) because Cartesia's own pricing page does not state a per-character rate, so **the Cartesia per-character figure is `unverified`**.

### The cost finding is that cost does not decide this

Assume this tool reads roughly 10,000 characters a day — a few documents of working prose — across 22 working days. That is **~220K characters a month**. (This volume is an **assumption**, not a measurement: I have no artifact recording actual throughput. See §6.)

At that volume:

| Option | Monthly cost |
|---|---|
| OpenAI `tts-1` | **~$3.30** |
| OpenAI `tts-1-hd` | ~$6.60 |
| Deepgram Aura-2 | ~$6.60 (`unverified` rate) |
| Cartesia | ~$8–11 (`unverified` rate) |
| ElevenLabs | ~$36–40 |
| **Kokoro (local)** | **$0** |

**Nothing here is expensive.** Even ElevenLabs at the top of the range is under a streaming subscription. **The cost axis does not discriminate between these options at this volume.** The decision rests entirely on confidentiality and licence, and both of those point local.

Anyone arguing for cloud on cost grounds is arguing about $3 a month. Anyone arguing for cloud on quality grounds is making a real argument, and it should be answered by trying Chatterbox first.

---

## 4. Recommendation

**Keep Kokoro-82M as the sole engine. Build the application so the engine is swappable, and do not wire in a cloud provider.**

The reasoning, in order of weight:

1. **Confidentiality is not satisfiable with any affordable cloud tier.** The best-sounding provider may train on the text below Enterprise; the cheapest credible one retains it for 30 days. There is no tier of any provider surveyed that is both cheap and zero-retention.
2. **Cost provides no counter-pressure.** At ~220K chars/month the entire cloud field costs between $3 and $40 a month. Nothing is being saved by accepting the disclosure, and nothing is being spent by refusing it.
3. **Latency and throughput are already solved locally.** Kokoro synthesises materially faster than realtime on Apple Silicon, so the queue design, not the engine, governs perceived responsiveness.
4. **Apache 2.0 matches the repo** and avoids the GPL question Piper raises and the non-commercial walls F5-TTS and XTTS-v2 hit.

### The strongest argument against this recommendation

**Kokoro is an 82M-parameter model and it will sound like one on hard text.** The application's actual workload is long technical prose dense with exactly the tokens small TTS models handle worst: internal identifiers like `ABC-12345`, PR numbers, `snake_case` symbols, acronyms, version strings, file paths. Reported MOS figures put Kokoro around 4.5 against roughly 4.8 for the best commercial models (`unverified` — these numbers come from SEO-heavy comparison sites, not from a benchmark I could verify, and I would not defend them).

If the real complaint after a week of use is *"it mispronounces every identifier and the prosody is flat over long paragraphs,"* that is a genuine quality gap and a 3.3× cost increase to `tts-1-hd` would be trivially affordable. **The counter-argument is defeated only by the confidentiality constraint, not by cost and not by quality.** That is worth being honest about: this recommendation trades some audio quality for a privacy property, and the trade is only obviously correct because of what this specific tool reads aloud.

**The mitigation is not a better engine. It is a pronunciation layer.** A user-editable lexicon that rewrites known identifiers before synthesis (`ABC-12345` → "A B C one two three four five", `featureflag` → "feature flag") will fix more of the perceived quality problem than any model swap, and it works with whatever engine is behind it. That belongs in the architecture regardless of this decision, and I would build it before I would re-open the engine question.

---

## 5. What would change this answer

Revisit if any of these become true:

- **An engine ships with a genuinely zero-retention free or cheap tier**, contractually, not as an enterprise upsell. That single change makes the cloud field competitive again overnight.
- **The tool stops reading confidential material.** If it is ever repurposed for public content only, the entire constraint evaporates and `tts-1` at $15/M becomes the obvious default.
- **Volume rises by two orders of magnitude.** At ~20M chars/month, ElevenLabs would cost ~$3,300/mo and local becomes a cost argument as well as a privacy one. This strengthens the recommendation rather than weakening it.
- **Chatterbox Turbo measurably beats Kokoro on this workload.** Same licence class, same locality, better voice: a straight upgrade with no constraint cost. **This is the most likely reason to revisit and the cheapest to test.**
- **Apple ships a materially better on-device TTS API.** Fully local by construction, no licence question, no retention question.
- **Kokoro's MLX/CoreML ports stall.** The Apple Silicon story depends on community ports rather than first-party support; there is at least one open report of NaN/silent output on an MLX build ([HF discussion](https://huggingface.co/mlx-community/Kokoro-82M-bf16/discussions/5)). If that path rots, the calculus changes.

---

## 6. What I could not establish

Typed honestly rather than guessed. These are not equivalent and each names a different fix.

- **James's actual character volume — `unknown`.** No artifact records it. The §3 figure of ~220K chars/month is my assumption for illustration, and every monthly cost above inherits it. **Fix: instrument the current shell-script setup for a week.** The conclusion is robust to this being wrong by 10× in either direction, but the specific dollar figures are not.
- **Perceived quality on *this* workload — `underdetermined`.** MOS numbers exist but I could not verify them against a primary benchmark, and MOS on read speech does not predict pronunciation accuracy on internal identifiers, which is what actually matters here. **Fix: A/B Kokoro against Chatterbox on a real report, by ear.** No amount of further desk research settles it.
- **Cartesia and Deepgram data-retention policies — `unverified`.** I did not reach their DPAs. Both may have better or worse postures than OpenAI's. Given the recommendation is local, this did not block the conclusion, but it would need doing before either was adopted.
- **Cartesia's per-character rate — `unverified`.** Their pricing page states credits, not characters; the 1:1 mapping is from a secondary source.
- **Streaming support for Chatterbox, Orpheus, CSM-1B, and Piper — `unverified`.** Not stated on the pages I reached.
- **Apple Silicon support for Orpheus, CSM-1B, and Piper — `unverified`.** Not stated on the pages I reached.

**Search frontier, stated so the absences above are readable:** I searched via WebSearch and fetched vendor pricing pages, HuggingFace model cards, and GitHub READMEs for the engines named in the brief. I did **not** read any vendor's DPA or Terms of Service in full, did not run any model, and did not conduct listening tests. So "I found no evidence of X" in this document means *"not present on the pages I reached,"* never *"X does not exist."* Several secondary sources that surfaced prominently — `localaimaster.com`, `codesota.com`, `spokio.pro`, `texttolab.com`, `elevenlabsmagazine.com` — appear to be SEO content operations rather than independent benchmarks; I have used them only where marked `unverified` and have not rested any conclusion on them.

---

## 7. One note for the architecture work

Not my file to edit, so recording it here: **the engine boundary should be an interface with one implementation, not an abstraction layer with a provider registry.** The recommendation is to ship exactly one engine. Building a plugin system for providers that should never be enabled creates the affordance for someone — plausibly a future agent — to wire in a cloud key and route confidential text through it because the seam was there and looked like an invitation.

If cloud is ever added, the guard belongs at the text boundary rather than the engine boundary: classify what a piece of text *is* before deciding what may speak it. An engine-level switch cannot tell a release note from an artifact audit; the caller can.
