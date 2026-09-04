# Synthesis artifact-fault evidence

Date: 2026-09-03

Change kind: bug fix

Oracle: only usable audio becomes Ready, and one artifact fault cannot stop
later queued work

## Red on the unfixed code

Commit `acc3426` adds two deterministic failures at the synthesis boundary.
The first engine reports success without creating its output. The unfixed pool
marks that item `Ready` with a path that does not exist. The second engine
writes a partial artifact and raises `OSError("seeded disk full")`; its cleanup
then raises `OSError("seeded cleanup failure")`. On the unfixed code, the bad
item remains `Synthesizing`, the following good item remains `Queued`, and the
worker task exits.

Both tests enter through `SynthesisPool` and observe stored lifecycle state and
whether the next queued item becomes Ready. They do not assert worker methods
or implementation choreography.

## Fix and calibration

`AudioArtifactPort` makes output targeting, usability validation, and disposal
an application boundary. `FileAudioArtifacts` is the filesystem adapter. The
pool now accepts `Ready` only after observing a regular non-empty artifact,
turns missing output into a typed item failure, and contains disposal errors so
later work continues.

Two independent mutations calibrated the assertions after the fix:

- forcing `is_usable()` to return true makes the missing-output test fail with
  `Ready` instead of `Failed`;
- allowing `discard()` to propagate `OSError` makes the stacked-fault test fail
  with the original wedged `Synthesizing` / `Queued` states and a stopped pool.

Both mutations were reverted before the GREEN verification.

## Remaining boundary

The seeded write and cleanup failures cover missing output, partial output, and
a cleanup fault stacked on an engine fault. They do not claim atomic artifact
publication across process crashes, exhaustive filesystem error simulation, or
a real volume driven to full capacity. Those cells remain explicit in the
release risk map.
