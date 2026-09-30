# PR 23 capture audit

Change-kind: refactor

The seven dispatch closures in `AppState.swift` implicitly retained `self`
while their nested main-actor tasks captured it weakly. Swift 6.4 diagnoses
that implicit ownership mismatch. Make the existing outer strong capture
explicit; retain the inner weak captures. No API, schema, or invariant changes.

## Compiler regression and falsification

Oracle: the Swift compiler's `ImplicitStrongCapture` diagnostic. This is a
medium, local compiler-boundary check, not a text assertion on implementation
syntax. The worktree owns its build products; no running daemon is involved.

On unmodified PR head `e435fb2`, from `clients/menubar`:

```sh
swift build -Xswiftc -warnings-as-errors
```

Exit 1, with `ImplicitStrongCapture` errors at lines 113, 190, 255, 274, 297,
314, and 378. With explicit outer captures, the same command exits 0 without
warnings. The unfixed compilation is the falsification witness. No new runtime
test or changed assertion is needed for an ownership-spelling refactor.
Retire this diagnostic check if the affected closures are removed or a stricter
compiler check subsumes it.

## Generated equivalence evidence

Compile all menu-bar sources before and after with the same Swift 6.4 compiler
and dependency modules, substituting only the parent `AppState.swift` for the
before run:

```sh
swiftc -emit-sil -O -whole-module-optimization -module-name AITTSMenuBar \
  -swift-version 5 -I clients/menubar/.build/debug \
  clients/menubar/Sources/AITTSMenuBar/*.swift
```

The parent source was exported into an isolated directory with the same basename.
Both compilations exited 0. Compare optimized SIL after removing comments and
canonicalizing generated UUIDs by first occurrence, preserving distinct UUID
identities (257 in each output). No instructions, symbols, literals, or control
flow are excluded. The complete normalized outputs match, SHA-256:

`eb31ee0bdbe8b727171c6486521cf2b65c01bc3df9e4a57172d620ec1e76a2b8`

This is compiler-generated differential evidence for this toolchain and release
optimization mode, not a cross-toolchain correctness proof. The unchanged debug
suite separately exercises the application boundaries.

## Validation and remaining blocker

- Full Python suite: 558 passed; Ruff check, Ruff format check, and mypy passed.
- Unmodified local Swift suite: 97 passed.
- After the capture edit, `swift build -Xswiftc -warnings-as-errors` passed.
- `python3 ../../scripts/run_with_deadline.py 60 swift test -Xswiftc
  -warnings-as-errors`: 97 passed, no warnings.
- Local environment: Xcode 27.0 (27A266a), Apple Swift 6.4.

Hosted CI run `35527119918` at `e435fb2`, using Xcode 26.3, crashed with signal
11 after starting the caption-preference test. This did not reproduce locally.
The capture cleanup is not evidence that the crash is fixed. Keep hosted CI as
a merge blocker until the new commit has its own passing run; do not retry the
old failure into green. A second independent approval is also required by the
requested merge gate. No unresolved inline review threads existed at audit start.
