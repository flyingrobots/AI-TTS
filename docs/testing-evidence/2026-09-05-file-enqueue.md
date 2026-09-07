# Menu-bar file enqueue evidence

Date: 2026-09-05

Change kind: feature

Oracle: the 2026-09-05 product decision that the menu-bar UI enqueue a local
text, Markdown, or PDF document while preserving the existing document queue,
confidentiality, and immutable-voice semantics.

## Boundary and risk decision

File selection is a menu-client adapter, not a new daemon operation. The app
receives one user-selected URL, extracts text locally, and sends an ordinary
`submit` payload. No filesystem path crosses the socket, so the daemon does
not gain authority to read arbitrary local files. The payload is explicitly
`confidential` and Normal priority; the daemon stamps its current voice and
generation speed once on the parent and applies its existing Markdown AST and
segmentation policy.

Plain text and Markdown require valid UTF-8 and retain exact source bytes after
decoding. PDFKit supplies text-layer content page-by-page with a blank-line
boundary between non-empty pages. This makes no layout-fidelity or OCR claim.
Password-locked and image-only PDFs fail locally with actionable guidance.

## RED: selected-file extraction and refusal contract

The contract enters through `SpeechFileImport.read`, the narrowest boundary
that owns local format recognition and extraction. Its medium tests create
owned temporary text files plus real text-bearing, image-only, and
password-locked PDFs. They observe the exact daemon submission projection or
the exact typed refusal.

With a deliberate no-extraction mutant that returned an empty import for every
file, this command exited 1:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechFileImportTests
```

All eight tests failed with zero unexpected failures. Text and Markdown lost
their source, the two-page PDF lost reading order, and empty, non-UTF-8,
image-only, locked, and unsupported files were incorrectly accepted. The
mutant was then removed.

The invalid-UTF-8 assertion was also calibrated independently by temporarily
switching to replacement-character decoding. Its focused test exited 1 because
the malformed file was accepted; strict UTF-8 decoding was restored before
the green run.

## GREEN: native picker admission

The Queue toolbar now exposes **Add file…** through SwiftUI's native file
importer. It allows one plain-text, Markdown, or PDF selection. Extraction runs
off the main actor, uses security-scoped access when supplied by macOS, and
submits only text plus a basename-derived local source label through the
existing daemon client. Selection and extraction failures use the existing
popover error surface.

The focused suite is green:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechFileImportTests
```

The complete Swift, Python, formatting, typing, distribution, and installed-app
verification receipts follow after final validation.

## Final verification

The final tree passed every configured release-candidate gate:

```console
uv run ruff check
# All checks passed!

uv run ruff format --check
# 85 files already formatted

uv run mypy
# Success: no issues found in 57 source files

uv run pytest
# 194 passed in 4.62s

cd clients/menubar
swift build
python3 ../../scripts/run_with_deadline.py 60 swift test
# 21 tests passed, including 8 SpeechFileImportTests

cd ../..
uv build --offline
# source distribution and wheel built successfully
```

The release bundle was rebuilt at
`~/Applications/AI-TTS.app`, passed `codesign --verify --deep
--strict`, and launched as the expected `com.flyingrobots.ai-tts.menubar`
accessory app. Its final executable was byte-identical to the separately built
and verified release candidate at SHA-256
`8d3bb920b87b412316b33081c662955ee82d5cfc8e20ace33bb7205efe6d632c`.
A live screen capture confirmed **Add file…** in the Queue toolbar. The user
closed the transient UI during the picker click-through, so no file was
selected and no claim is made for a retained end-to-end picker screenshot.
Automated accessibility journeys remain the testing profile's explicit
menu-app blind spot.
