# JSONL parser evidence

Date: 2026-09-03

Change kind: bug fix

Oracle: daemon JSONL wire contract in `docs/design/architecture.md` section 5

## Red on the unfixed code

Commit `8b959d7` records two socket-level regressions before the fix:

- an invalid UTF-8 line raises an unhandled `UnicodeDecodeError`, returns no
  typed error, and closes the connection;
- a valid 70 KiB request is below the daemon's 1 MiB limit but raises
  `ValueError` inside `StreamReader.readline()` because asyncio silently uses a
  64 KiB default limit.

Both tests fail on that commit with an empty response, directly contradicting
the protocol's never-empty-response promise.

## Generated evidence and permanent corpus

The strict codec is a transport adapter shared by the socket server and client.
Its deterministic Hypothesis campaign runs:

- 200 recursively generated JSON objects through encode/decode round trips,
  asserting one physical output line and exact semantic equality;
- 500 arbitrary byte strings through the decoder, asserting that every input
  yields either an object or a named `JsonlDecodeError`, never an unexpected
  exception.

The minimized checked-in corpus under `tests/corpus/jsonl/` permanently replays
valid object, malformed JSON, invalid UTF-8, non-finite number, and non-object
seeds. Hex encoding preserves malformed bytes as portable text.

## Assertion calibration

Each new load-bearing assertion was made red independently and restored:

1. removing the encoder's terminal newline made the generated round-trip test
   shrink to `{}` and fail on both terminator and physical-line count;
2. allowing `ValueError` to escape made the explicit `ff 0a` seed fail with
   `UnicodeDecodeError` in the arbitrary-byte test;
3. removing strict non-finite parsing made the permanent `NaN` seed decode as
   an object and fail its typed-error expectation.
4. adding an unlisted valid seed made the corpus-ledger check fail and name the
   exact orphaned `unlisted.hex` asset.
5. suppressing the over-limit error reply made the socket contract receive an
   empty line and fail while decoding the missing response.

The two socket regressions provide the red-on-parent calibration for invalid
UTF-8 handling and the stream limit. The encoder's strict-value rejection is
calibrated by the existing `allow_nan=False` branch: changing it to true makes
the `nan` and infinity cases fail to raise.

The first full-suite run also caught an adapter-package import cycle through
the isolated wheel and process-lifecycle contracts. Removing unused eager
package re-exports restored direct, acyclic imports; the focused codec tests
alone could not have supplied that integration evidence.
