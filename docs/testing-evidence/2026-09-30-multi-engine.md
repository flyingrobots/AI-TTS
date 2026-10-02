# Multi-engine registry acceptance

Change-kind: feature

Prompt 4 includes a frozen native installation path and real offline inference.
The source-package audit method and its limits are recorded below. The installed
application has not been replaced by this branch.

## Implemented contract

- Each accepted clip persists its engine. Segments inherit the parent choice,
  recovered work retains it, and replays preserve it. Existing databases gain a
  nullable column; legacy rows bind once to the startup backend.
- Defaults switch live. An explicit request overrides that default. Settings
  validate a simultaneous voice change against the requested engine before
  applying either change. Stale saved voices report a speakable fallback.
- Resident engines have independent cold/loading/ready/failed/reloading states.
  Preparation is serialized per engine and failures require an explicit retry.
- Private text is checked at admission and again at the synthesis boundary.
  A local HTTP adapter pins loopback, ignores ambient proxies, refuses redirects,
  bounds bytes, verifies complete WAV output and removes failed candidates.
- The CLI lists engines and accepts all three settings forms. The composer uses
  the wire catalog and clears voices incompatible with a new model.
- External servers are reported as server managed, not hot, and their model
  restart is not represented as a successful local operation.

## Evidence and falsification

Tests enter through Store, Engine, SynthesisPool, Daemon dispatch, the CLI and the
Swift snapshot/draft boundaries. Owned loopback servers provide exact JSON/WAV
oracles; fake sinks and a controlled warmup gate avoid physical audio and scheduler
races. Temporary stores test reopen, legacy migration, and seeded commit rollback.
The new Python tests are medium with named oracles. Swift uses the existing
15-second per-test and 60-second process deadlines.

Initial missing-API failures are scaffolding evidence only. Load-bearing checks
were subsequently calibrated with behavioral faults. The retained
[calibration record](2026-09-30-multi-engine-calibration.json) includes wrong-engine
routing, lost child choice, privacy checks removed at each boundary, overwritten
legacy choices, rollback removed, ignored CLI switches, old-model voice validation,
repeated warmup, forgotten failure, incorrect HTTP arguments/duration, partial
artifacts, non-loopback routes, ignored byte bounds, lost localhost pin, false
external readiness, changed native samples/rates, ignored native speed/assets,
missed reload, missing Swift catalog, and inverted voice reconciliation. Each
fault produced a named assertion failure and was restored.

The stale saved-voice case was observed red with `old-backend-voice` instead of
`new-backend-voice` before the fix (`/tmp/registry-stale-voice-red.log`). A failed
model preparation initially left no clip-local failure record; its test observed
an empty log, then passed after preparation moved inside the per-clip evidence
lifecycle (`/tmp/registry-warmup-evidence-red.log`). Legacy
migration preserves source/sensitivity; the commit-failure test witnesses an
uncommitted binding and verifies rollback before a subsequent valid binding.

Final draft verification: **687 Python tests passed** with an empty Hypothesis cache in 9.30 seconds wall clock
(228 small / 459 medium; 0.57 / 8.23 seconds by tier, within 10 / 45-second budgets). **113 Swift
tests passed** under the 60-second process deadline. Ruff, format checks, mypy
(117 source files) and diff checks passed. Full receipts:
`/tmp/multi-engine-cold-python-final.log` and `/tmp/multi-engine-swift-final.log`.

Existing IPC expectations intentionally now report actual registered engine names
instead of the old `local` placeholder, and settings report the live selected
backend instead of an unrelated persisted/default name. Other existing assertions
were retained; CLI fixtures now register a second owned backend so switch tests
cannot pass by selecting an already-selected default.

Delete or change these tests when their external contract changes. No coverage or
mutation percentage is an acceptance goal. Contract doubles do not establish
real model quality, latency, or third-party compatibility.

## Chatterbox dependency finding

The official Chatterbox Turbo implementation is the 350M model and exposes
`ChatterboxTurboTTS.from_local` plus mono 24 kHz tensor output. The draft adapter
uses an explicit complete local snapshot, never calls `from_pretrained`, preserves
its native output including the watermark, and rejects unsupported generation
speeds before synthesis. Eight controlled loader/tensor tests pass. Real-model
inference was subsequently exercised in the isolated experiment below.

Published `chatterbox-tts==0.1.7` pins torch 2.6 on Python below 3.14. A separate
Python 3.14 dependency experiment avoided that pin but still failed the required
vulnerability audit: **25 advisory records across four packages** (records include
duplicate advisory aliases). Affected pins were diffusers 0.29.0, gradio 6.8.0,
transformers 5.2.0, plus transitive starlette 0.52.1. The experiment and its base
package downgrade were removed from `uv.lock`; no vulnerable extra was retained.
Raw local receipts: `/tmp/chatterbox-audit.json`, `/tmp/chatterbox-audit.log` and
`.git/codex-scratch/chatterbox-experimental.lock`.

The subsequent upstream-source installation below resolves this packaging problem
without maintaining a separate fork or deferring the requested adapter.
Primary upstream references:
[API implementation](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/tts_turbo.py),
[published package](https://pypi.org/project/chatterbox-tts/0.1.7/).


## Isolated native inference experiment

The dependency-only upstream [PR 486](https://github.com/resemble-ai/chatterbox/pull/486),
at `cb240457c3e197c6fbc2e7d3b9765febe63f7e73`, resolves on Python 3.14.7 to a
PyPI dependency graph with no known vulnerabilities in the audit at experiment time.
It imports with torch 2.14.0, torchaudio 2.11.0, transformers 5.17.0 and diffusers
0.40.0. TorchAudio 2.11 supports newer PyTorch through its stable ABI per the
[upstream compatibility documentation](https://docs.pytorch.org/audio/master/installation.html).

The first real warmup failed: released resemble-perth 1.0.1 catches its missing
`pkg_resources` import and exposes a non-callable watermarker. The experiment then
installed the upstream Perth fix at `ff1c8ac55a976971245cdd53c18d6131ca00d993`
(version 1.1.0), retaining all other resolved versions. No watermark bypass,
setuptools downgrade, or application monkeypatch was used.

With that source revision, the actual AI-TTS adapter loaded a pinned Turbo snapshot,
primed once, and generated "This is a controlled local speech synthesis test."
Offline environment flags and denial hooks on Python socket connection and DNS
operations were installed before importing the adapter; no attempts were observed.
The result was a finite, nonzero, mono 24 kHz float WAV: 68,160 frames / 2,840 ms.
CPU warmup took 9.04 seconds and synthesis 1.77 seconds in this single observation.
No audio was played. This is a manual, non-gating large experiment; these timings
are not a performance promise or a latency benchmark. The
[receipt](2026-09-30-chatterbox-native.json) retains model/source revisions,
asset fingerprints, measured output properties and the WAV digest.

This initial experiment proved native inference for that isolated combination,
before the frozen package-delivery work below. The PyPI audit predates replacing Perth and does not audit either Git
source revision. The Chatterbox dependency proposal remains unmerged. The subsequent frozen-install section below records the installation, inventory
and audit integration. The installed application remains unchanged. Local scripts,
resolved requirements, logs and audio are under `.git/codex-scratch/chatterbox-*`.


## Hosted fixture correction

The first hosted run, 36717887022, passed Swift and dependency audit but exposed
an ambient dependency in the owned HTTP fixture: stdlib `HTTPServer.server_bind`
called `socket.getfqdn`, which blocked in reverse DNS and exceeded the test's
15-second ceiling. That stall also exhausted the medium-tier budget. The run was
not retried unchanged and no budget was raised.

A controlled resolver witness first observed `['127.0.0.1']` instead of no DNS
lookups (`/tmp/registry-server-dns-red.log`). The fixture now binds with
`TCPServer.server_bind` and assigns its known local server identity directly.
The witness and all 687 Python tests pass after this correction. This restores
the fixture's intended hermetic boundary; it does not change production routing.


## Cold Unicode generation correction

The next hosted run, 36718394241, passed all HTTP tests, Swift and audit, but the
pre-existing schema round-trip property exceeded its 2-second small-test ceiling
inside Hypothesis. Its timeout subsequently appeared as `FlakyStrategyDefinition`.
The input oracle itself did not fail. The run was not retried unchanged.

Controlled fresh-cache profiling attributed 1.307 seconds to
`charmap.intervals_from_codec` and 0.192 seconds to the Unicode category map;
the single property cost 1.64 seconds under profiling on this Mac. These routines
scan the Unicode domain and write an ambient codec cache. They explain why a warm
developer run hid a cold-runner dependency.

`tests/strategies.py` now maps bounded integers bijectively onto Unicode scalar
values, skipping the surrogate interval, then builds bounded strings. All three
generated text suites use it. The legal scalar domain, maximum string lengths,
example counts (100 schema, 200 JSON round-trip, 50 adapter), deterministic seeds,
assertions, size classes and deadlines remain unchanged. Fresh-cache profiling
observed 0.22 seconds for the schema property and no charmap construction calls.
The full empty-cache run passed all 687 tests. Profiling numbers are diagnostic
observations, not new performance gates.

The three unchanged property oracles were recalibrated with dropped schema voice,
missing JSONL terminator and missing adapter arguments. Each produced its named
assertion failure; all faults were restored. The retained calibration record
includes these cases. No test was skipped or moved into a looser size class.


## Frozen native installation and source audit

The `chatterbox` extra now pins both upstream source archives above, including
SHA-256 digests in `uv.lock`. Incremental resolution preserved existing pins
where compatible. An isolated Python 3.12 all-extras environment was installed
with `uv sync --frozen --all-extras --no-dev --group supply-chain` and exercised
through the same real adapter. It generated 68,160 finite, nonzero mono samples at
24 kHz, with zero observed socket/DNS attempts and native watermarking intact.
The frozen graph used torch 2.13.0; observed CPU warmup was 33.05 seconds and
synthesis 1.77 seconds. This cold-environment observation is not comparable to
the earlier warm-import experiment. The [frozen receipt](2026-09-30-chatterbox-frozen.json)
records the environment and output digest.

Strict hashed PyPI auditing remains enabled for every registry dependency.
Only the two explicitly pinned source packages take a separate path: their
name/version/archive URL/hash must match the validated source policy; unknown
or changed sources fail. OSV is queried by both exact commit and package/version.
Responses, queries, source identities, and the limitation that empty results do
not prove advisory coverage or code security remain in the combined audit JSON.
Findings feed the existing failing vulnerability gate; transport or malformed
service responses fail instead of becoming clean evidence. Both source packages
participate in the existing SBOM and license cross-checks.

Local complete-graph evidence: **161 dependencies, 161 license records, 186 SBOM
components, zero known advisory findings**. The sole unknown license remains
`espeakng-loader`, the pre-existing distribution review item. The source packages
are MIT. Evidence is retained under `.git/codex-scratch/native-evidence` and
`native-release-{audit,sbom,licenses}.json`.

Thirteen small source-evidence boundary tests cover source identity, unlisted
packages, both advisory queries, finding propagation, malformed/failed queries,
and inventory inclusion. Nine seeded faults each produced named failures in the
[source calibration receipt](2026-09-30-source-audit-calibration.json); sources
were restored and all tests passed. Delete these tests if source dependencies
return to registry releases and this audit path is removed.

Final packaging validation: **700 Python tests passed**, 241 small / 459 medium,
1.25 / 8.39 seconds by tier, 10.68 seconds wall clock. Ruff, formatting and mypy
(119 files) passed. Swift sources are unchanged from the 113-test passing run.

## Integration with reviewed main

Replayed onto main `6482b49`, retaining validated-before-assignment admission,
platform factory boundaries, and the native provenance/composer corrections.
Engine resolution occurs before checking supported generation speeds; voice
assignment remains after validating speakable content and uses the selected
engine's catalog. The integrated multi-engine stage passed 751 Python tests.

A warnings-as-errors Swift build failed on the two old single-argument
`onChange` overloads introduced by the model picker. Both now use the supported
macOS 14 zero/two-argument forms with the same reconciliation behavior.
The original compiler failure is the red witness; no artificial source-text
assertion was added.
The corrected integrated stack passed all 142 Swift tests with warnings as errors.

## Code Lawyer review round (October 1)

Merge `518fb9f` brought in main `3aa9cec`: #34's final streaming version, plus #56, #57, #64, #48 and #55. Each fix below is a bug fix with a regression test observed red on its parent.

Startup warmup holds only its own engine (`Change-kind: bug fix`, review thread `PRRT_kwDOUHyfMM6njsQp`). Before this fix, `_run_synthesis` did not start the pool until the startup engine's warmup finished, so a clip routed to another registered engine stayed Queued behind an unrelated model load. The medium `test_startup_warmup_holds_only_its_own_engines_clips` wedges the startup engine's warmup and submits a clip for a second engine. It was red on parent `518fb9f`: `AssertionError: condition not met before timeout` while waiting for the second engine's clip to become Ready. The pool now starts immediately, and the claim query skips only the startup engine's work until its warmup ends. The existing `test_daemon_keeps_source_queued_until_warmup_finishes` still passes unchanged, so the startup engine's text still stays Queued until its preparation finishes. Oracle: the PR's contract of independent per-engine preparation.
