# Native macOS hexagonal-boundary evidence

Date: 2026-09-05

Change kind: feature

Oracle: the native client must expose one reusable selected-document use case
to menu-bar and future OS inbound adapters, while filesystem/PDF and daemon-wire
details remain replaceable outbound adapters.

## Boundary and risk decision

The Python speech application already had an agent-facing
`SpeechServicePort`, with MCP and Unix-socket adapters outside its public
schemas. The native Swift client did not have the equivalent dependency shape:
`AppState` constructed a concrete `DaemonClient`, assembled raw daemon
dictionaries, decoded responses, and invoked the PDFKit-backed file importer
directly. A Finder or Services target would therefore have duplicated policy or
depended on presentation code.

The Swift package now has three compile-time boundaries:

- `AITTSApplication` contains public immutable models, the
  `DocumentEnqueueing` inbound port and `EnqueueDocument` use case, plus
  `SpeechDocumentReaderPort` and `SpeechServicePort` outbound ports. It imports
  no AppKit, SwiftUI, PDFKit, socket client, or daemon wire codec.
- `AITTSMacAdapters` implements the outbound ports. It alone owns selected-file
  security scope, UTF-8/PDFKit extraction, daemon dictionaries, NDJSON, Unix
  socket I/O, and response projection.
- `AITTSMenuBar` is the AppKit/SwiftUI inbound adapter and composition root. Its
  `AppState` depends only on typed ports and the document-enqueue use case.

The menu composition supplies `menubar-file` as provenance, preserving the
existing history source. A future Finder, Services, or Shortcuts target can
compose the same `EnqueueDocument` type with its own provenance prefix. The OS
adapter itself is intentionally not implemented by this change.

## RED: document admission policy

The contract enters through `EnqueueDocument.enqueueDocument(at:)`, the
narrowest boundary that owns document admission policy. Its reader and speech
service are controlled fakes. The first implementation deliberately submitted
empty public text at Urgent priority with an unqualified filename source.

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechApplicationTests
```

The command exited 1. The single assertion reported all four intended
differences: empty rather than exact text, `public` rather than `confidential`,
`urgent` rather than `normal`, and `revenue.md` rather than
`menubar-file:revenue.md`.

## RED: typed daemon mapping

The second contract enters through `UnixSocketSpeechService`, using an owned
raw-transport fake. It observes exact canonical JSON requests for submission
and every query/transport/settings command, typed error translation, snapshot
projection, omitted optional fields, and event-to-change notification.

With a deliberate mutant mapping `.clearQueue` to the history queue, this
command exited 1:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter UnixSocketSpeechServiceTests
```

Five tests passed and exactly the command-projection test failed. Its diff
isolated `{"op":"clear","queue":"history"}` where the oracle required
`{"op":"clear","queue":"queue"}`. The mutant was then removed.

## GREEN: interchangeable native adapters

Focused application, wire-adapter, and real local-document suites passed with
the final implementation. The complete Swift suite then passed 28 tests behind
the repository's 60-second process-group deadline.

Swift Package Manager reports the intended dependency DAG:

```text
AITTSApplication -> []
AITTSMacAdapters -> [AITTSApplication]
AITTSMenuBar -> [AITTSApplication, AITTSMacAdapters]
```

Mermaid CLI found and rendered both diagrams in `architecture.md`, including
the native-client hexagon and its dashed planned OS adapter.

## Final verification

The final tree passed every configured release-candidate gate:

```console
uv run ruff check
# All checks passed!

uv run ruff format --check
# 86 files already formatted

uv run mypy
# Success: no issues found in 57 source files

uv run pytest
# 194 passed in 4.92s

cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test
# 28 tests passed

swift build -c release --product AITTSMenuBar
# Build of product 'AITTSMenuBar' complete!

cd ../..
uv build --offline
# source distribution and wheel built successfully
```

The release bundle replaced only `~/Applications/AI-TTS.app`, passed
`codesign --verify --deep --strict`, and launched beside the unchanged daemon.
Its installed executable was byte-identical to the separately built and signed
candidate at SHA-256
`2c20352cc13199d2c98cd7682e5980568e7d2e3beb8abd81c9622f85b6908d72`.
The live daemon remained on its original process and returned `ok: true`,
`state: accepting`, and `playback_state: idle` after the app restart.
