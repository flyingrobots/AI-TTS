# Bounded native document-reading evidence — 2026-09-05

Change kind: feature

Oracle: the local-file adapter must bound user-selected document acquisition
before the architecture section 5 one-MiB serialized-request boundary

## Boundary and limits

`LocalSpeechDocumentReader.read(_:)` is the narrowest contract that owns file
bytes and PDFKit extraction. The default `v0.1.0` budget accepts:

- up to 512 KiB of UTF-8 plain text or Markdown;
- a PDF source up to 32 MiB and 500 pages;
- up to 512 KiB of page-ordered extracted PDF text, including inserted page
  separators.

The adapter reads source data in bounded 64 KiB chunks and retains at most one
byte beyond a source limit to distinguish exact-limit acceptance from the first
excess byte. PDF page count is checked before extraction, and extraction stops
at the first page that would exceed its UTF-8 budget.

## Falsification before enforcement

The limits and typed errors were first added as an unused injection seam so the
contract could compile without changing behavior. The focused suite then
exited 1 with four expected failures:

```text
python3 ../../scripts/run_with_deadline.py 60 swift test \
  --filter LocalSpeechDocumentReaderTests
Executed 12 tests, with 4 failures
```

- nine bytes were accepted through an eight-byte text limit;
- an oversized malformed PDF reached PDFKit and returned `unreadablePDF`
  instead of failing at its source-byte boundary;
- three pages were accepted through a two-page limit;
- nine extracted bytes were accepted through an eight-byte limit.

After enforcement was implemented, all 12 focused tests passed.

## Inclusive-edge calibration

Three temporary off-by-one mutants independently changed source bytes, page
count, and extracted bytes from inclusive `<=` boundaries to `<`. In one
focused run, exactly eight text bytes, exactly two PDF pages, and exactly eight
extracted bytes were all rejected; the three corresponding tests failed and
named the unexpected typed error. The comparisons were restored, and the same
focused suite returned to 12 passing tests.

## Default and refusal-message calibration

The documented default budget is itself an executable contract. A temporary
one-byte increase to the standard text ceiling made
`testStandardLimitsMatchTheDocumentedV010Contract` fail with the observed
524,289 bytes versus the required 524,288 bytes. Restoring the value returned
that check to green.

Three temporary wording mutants changed the file-size, PDF-page, and extracted
text refusals. The 13-test focused suite exited 1 with exactly three failures,
each at its exact `localizedDescription` assertion. Restoring the actionable
messages returned the full focused suite to green.

## Final verification

The restored exact tree passed:

- 13 focused document-reader tests;
- 71 full Swift tests under the repository's 60-second deadline;
- 218 Python tests;
- Ruff lint and format checks, strict mypy, `uv lock --check`, and
  `git diff --check`;
- an offline wheel-and-sdist build accepted by `check-wheel-contents` and
  `twine check`;
- a production Swift app-bundle build accepted by `codesign --verify --deep
  --strict` and `plutil -lint`.

## Remaining boundary

The source byte ceilings bound data handed to PDFKit and string decoding, and
the page loop stops between pages. PDFKit still materializes the text string of
one admitted page before its UTF-8 size can be checked, so this does not claim
streaming within a page or defense against every decompression-bomb shape. The
32 MiB source ceiling bounds the upstream artifact; cancellation and an
extraction-time budget remain possible post-`v0.1.0` hardening.
