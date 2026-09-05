# Native macOS entry-point evidence

Date: 2026-09-05

Change kind: feature

Oracle: explicit native OS actions must delegate to shared application use
cases so selected text is exact, confidential, Normal, and literal while
selected files retain the existing document admission policy.

## Slice 1: selected-text application policy

The selected-text contract enters through
`EnqueueSelection.enqueueSelection(_:source:)`, the narrowest boundary that
owns how arbitrary highlighted text becomes speech. Its medium Swift tests use
an owned recording `SpeechServicePort`; they observe the exact typed
`SpeechSubmission` or an exact typed refusal without AppKit, a pasteboard, a
socket, or the daemon.

### Falsification

A deliberate admission mutant submitted an empty Markdown utterance as public
and Urgent with no source, and did not reject whitespace-only input. This
command built the mutant and ran the focused contract:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechApplicationTests
```

The document test passed, while both new selection tests failed with three
assertion failures and zero unexpected failures. The first diff exposed all
five corrupted observations: empty rather than exact text, `markdown` rather
than `plainText`, `public` rather than `confidential`, `urgent` rather than
`normal`, and `nil` rather than `macos-service:text`. The second test reported
that no error was thrown and showed the unexpected submission instead of an
empty recording. The mutant was then removed.

### Green

The final use case checks a trimmed copy only to reject empty or whitespace-only
input. It submits the original string unchanged with literal format,
confidential sensitivity, Normal priority, unset voice and speed, and the
adapter-provided source. The focused suite passed all three application tests,
and the complete suite passed all 30 Swift tests:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechApplicationTests
# Executed 3 tests, with 0 failures

python3 ../../scripts/run_with_deadline.py 60 swift test
# Executed 30 tests, with 0 failures
```

`swift format lint --strict -r Sources Tests` was inspected but is not a
configured repository gate. It reports the existing four-space codebase as
violating the tool's default two-space indentation throughout both untouched
and changed files; no bulk reformat or baseline change was made.

## Slice 2: native Services adapter and declaration

The Services adapter enters through an isolated `NSPasteboard` and delegates
to `SelectionEnqueueing` or `DocumentEnqueueing`, the narrowest boundary that
owns the native-to-application transition. Its medium Swift tests observe the
exact cross-boundary request or an exact typed refusal. The bundle contract
test parses the generated `Info.plist` and observes the two service
declarations macOS uses for discovery.

### Falsification

A deliberate inert adapter exported both Objective-C selectors but ignored
the request pasteboard and never called either application port. The app-bundle
builder deliberately omitted `NSServices`. These focused commands exercised
those mutants:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter MacServiceProviderTests
# Executed 6 tests, with 5 failures (0 unexpected)

cd ../..
.venv/bin/pytest -q tests/test_distribution.py::test_app_bundle_advertises_native_text_and_file_services
# 1 failed: generated Info.plist had no NSServices key
```

The Swift failures specifically reported the absent exact selected-text
request, absent single-file request, missing no-text error, and missing zero-
and multiple-file refusals. Selector discovery still passed, proving the
behavioral failures were not compilation or selector failures. The Python
failure compared `None` with the exact two-entry Services declaration. The
mutants were then removed.

### Green

The final provider reads one exact string or one file URL from the private
request pasteboard, delegates through the matching application port, and maps
local or downstream failures back to the Services error pointer. The
composition root retains and registers that provider after launch. The bundle
builder emits exact plain-text, Markdown-file, and PDF-file declarations.

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter MacServiceProviderTests
# Executed 6 tests, with 0 failures

python3 ../../scripts/run_with_deadline.py 60 swift test
# Executed 36 tests, with 0 failures

cd ../..
.venv/bin/pytest -q
# complete Python suite passed

uv run ruff check
# All checks passed!

uv run ruff format --check
# 89 files already formatted

uv run mypy
# Success: no issues found in 57 source files
```

## Slice 3: installed Services acceptance

No new automated assertion was introduced in this slice. This is large,
machine-specific acceptance evidence for the exact committed implementation at
`8129da7`.

The release builder created an ad-hoc-signed candidate outside the checkout.
`codesign --verify --deep --strict` passed, and AppKit's own Services database
parser accepted both entries. The candidate then replaced only
`/Users/james/Applications/AI-TTS.app`; the previous bundle was retained in the
owned temporary acceptance directory as a rollback copy. The installed
executable was byte-identical to the candidate at SHA-256
`05339e100864ab8c02278ad42c2787257971499528c466136b8a2d4138886d56`.

After Launch Services refresh and app restart, `pbs -dump` reported both
installed entries against bundle identifier
`com.flyingrobots.ai-tts.menubar` and path
`/Users/james/Applications/AI-TTS.app`:

- **Read Selection with AI-TTS**, message `readSelection`, sending
  `public.utf8-plain-text`;
- **Read File with AI-TTS**, message `readFile`, sending
  `public.plain-text`, `net.daringfireball.markdown`, or `com.adobe.pdf` files.

The preflight daemon was accepting, idle, unheld, and had no queued item.
Playback was held only for the acceptance requests. A named request pasteboard
then invoked each installed command through `NSPerformService`:

| Invocation | System result | Daemon observation | General pasteboard |
|---|---|---|---|
| exact selected text `AI-TTS native Service acceptance 8129da7.` | `performed=true` | one Ready, confidential, Normal, literal item from `macos-service:text` | change count `268` before and after |
| one Markdown file | `performed=true` | one Ready, confidential, Normal document retaining exact Markdown source from `macos-service:file:service-acceptance.md` | change count `268` before and after |
| two supported files | `performed=true` | no third item; the two-item queue remained unchanged | change count `268` before and after |

The two acceptance items were cancelled by their exact ids, playback was
restored to unheld, and the final queue was empty. The existing daemon process
was not restarted or replaced.

This proves installed registration and dispatch independently of any one host
application. It does not prove where TextEdit, Safari, Chromium, VS Code,
Preview, or Finder chooses to place an applicable Service in its menus, nor an
assigned keyboard shortcut. That representative host matrix remains open and
must not be inferred from the successful programmatic invocations.
