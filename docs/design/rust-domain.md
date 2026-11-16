# Rust domain contract

Status: implementation in progress for [issue #130](https://github.com/flyingrobots/AI-TTS/issues/130).

`aitts-domain` will contain deterministic rules and value types for the Rust daemon.
It will not operate storage, engines, sockets, devices, or the playback conductor.
The Python implementation remains the production path.

## Scope and verification plan

| Module | Contract | Verification |
| --- | --- | --- |
| `utterance` | Accept exactly the Python state transitions | Complete transition table and generated sequences |
| `plan` | Preserve queue order, priority, and nested preemption | Equal-key stability and nested interruption cases |
| `segmentation` | Preserve the recorded spoken segments | All 40 existing golden cases and word-preservation properties |
| `voices` | Preserve pinned, requested, and claimed voice precedence | Voice ownership and catalog exhaustion cases |
| `settings` | Validate setting values without applying effects | Inclusive limits, malformed values, and typed errors |
| `retention` | Select eligible retained artifacts without deleting them | Protected artifacts, byte limits, and deterministic ordering |
| `sensitivity` | Refuse confidential text for a remote engine | Complete sensitivity and engine-locality table |

Tests will enter through the public crate API.
Expected segmentation data remains unchanged.
The crate will have no runtime dependency on an I/O component.
Caller-supplied values will replace clocks, identifiers, catalog reads, and persistence queries.

The Rust workspace will pin its toolchain and lock dependencies.
CI will check formatting, strict Clippy, tests, and release-mode arithmetic behavior.
An evidence record will state the observed RED-to-GREEN results and assertion calibration.

This plan is agent-written. It does not claim completed implementation or human acceptance.
