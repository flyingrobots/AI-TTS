# Concurrent phonemizer state isolation

Change-kind: bug fix

## Reproduction and root cause

A selected document failed with `number of lines in input and output must be
equal, we have: input=1, output=4`. The installed Kokoro pipeline reuses one
Misaki/eSpeak phonemizer per language. eSpeak's pre/postprocessing stores input
and output word-count arrays on that shared instance, so concurrent segment
workers can overwrite each other's per-call state.

The two affected segments passed sequential phonemization. Concurrent calls
through the same real quiet Kokoro pipeline reproduced the corresponding
`input=4, output=1` failure on the third iteration. Source text was read locally
and is not recorded here or in the regression test.

## Regression boundary and controlled schedule

`tests/test_engine_phonemizer_concurrency.py` is medium and calls the public
`KokoroEngine.synthesize` boundary with a fake upstream pipeline/model. Its
oracle is the exact audio produced for two distinct synthetic phoneme inputs.

An event-controlled upstream double holds the first phonemizer call while the
second arrives. On unfixed code at `ea1e708`, the first WAV contained the second
call's value: approximately 0.4 instead of 0.1. This was an assertion failure,
not a timeout or import error. The fixed adapter protects phonemization with a
shared gate, and the two WAVs contain their respective 0.1/0.4 values.

The gate witness identifies an actually blocked competitor; no settle-time sleep
is used as an absence oracle. A barrier after phonemization additionally requires
both calls to reach neural rendering concurrently, so serializing the entire
pipeline would fail this schedule. Timeouts bound deadlocks; they are not the
success signal.

## Fix and acceptance

Wrap each newly constructed pipeline's G2P callable with a process-wide lock.
Release the lock before inference, file encoding, or playback. Sharing it across
languages also avoids simultaneous calls into native phonemizer state.

- The new regression and existing engine tests pass (12 targeted tests).
- Thirty repeated concurrent real phonemization runs of the affected segments
  completed without a mismatch after applying the production wrapper.
- Both affected segments synthesized concurrently through the real model into
  owned temporary WAVs: 2900 ms and 23925 ms, 24 kHz, finite samples. Temporary
  audio was removed afterward; no user speech was replayed during acceptance.

This fixes the reproduced selection failure. It does not establish the cause of
every intermittent audible pop reported in #25.
