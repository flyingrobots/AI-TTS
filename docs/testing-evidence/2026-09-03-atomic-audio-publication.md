# Atomic audio-publication evidence

Date: 2026-09-03

Change kind: bug fix

Oracle: architecture sections 3 and 6 require that only complete, published
audio can become Ready or appear in the bounded cache

## Red on the unfixed code

Commit `112b70b` introduces a blocking engine that writes only `b"partial"`
and then exposes the filesystem while synthesis is still in flight. The
unfixed implementation writes directly to `<utterance-id>.wav`, so
`FileAudioCache.inventory()` reports the partial file as published audio.

The second regression writes an unpublished candidate, constructs a fresh
filesystem adapter as a restart stand-in, and observes that preparation leaves
the abandoned file behind. Both assertions fail on `112b70b` while the normal
completed artifact remains correct.

A third regression was also observed red against the same production code: a
one-shot atomic-rename failure was never called, so the affected item was
incorrectly marked Ready instead of Failed.

## Fix and fault isolation

`AudioArtifactPort` now separates engine target selection from publication.
`FileAudioArtifacts.target()` returns a deterministic hidden `.wav.part` path,
and `publish()` uses same-directory `Path.replace()` to expose the canonical
WAV atomically. Cache inventory accepts only top-level `*.wav`, and adapter
preparation sweeps stale candidates left by process loss.

The synthesis pool contains failures from every artifact operation. Missing or
unusable output, target preparation, validation, atomic rename, and cleanup all
become per-item failure evidence; none can silently promote a candidate or stop
the next queued item.

The one-shot rename fault now produces:

- the first item as `Failed` with
  `artifact publication failed: seeded atomic rename failure`;
- the second item as `Ready`;
- a still-running synthesis pool.

## Remaining boundary

Same-directory replace provides atomic namespace visibility across a process
crash: observers see the old complete WAV or the new complete WAV, never the
candidate. This test does not claim persistence through sudden power loss,
file-and-directory `fsync` ordering, torn SQLite/WAL writes, or a real volume
filled to capacity. Those require a lower-level filesystem fault harness.
