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
`~/Applications/AI-TTS.app`; the previous bundle was retained in the
owned temporary acceptance directory as a rollback copy. The installed
executable was byte-identical to the candidate at SHA-256
`05339e100864ab8c02278ad42c2787257971499528c466136b8a2d4138886d56`.

After Launch Services refresh and app restart, `pbs -dump` reported both
installed entries against bundle identifier
`com.flyingrobots.ai-tts.menubar` and path
`~/Applications/AI-TTS.app`:

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

### Host-menu observation

One controlled TextEdit document was opened with the canonical sentence
selected. TextEdit's live application menu exposed an enabled
**TextEdit → Services → Read Selection with AI-TTS** item. The command was not
invoked again because installed dispatch had already been proven separately.

| Host | Surface | Result |
|---|---|---|
| TextEdit | selected text in application Services menu | Pass: command present and enabled |
| Safari | selected text | Not run |
| Chromium | selected text | Not run |
| VS Code | selected text | Not run |
| Preview | selected PDF text | Not run |
| Finder | selected supported file | Not run |
| Assigned keyboard shortcut | selected text | Not run |

The foreground TextEdit launch changed focus and captured unrelated keystrokes
before the fixture's purpose was understood. The controlled document was
closed without saving, and foreground host automation stopped. The remaining
matrix requires an explicitly coordinated interactive session or an isolated
GUI test session; it will not be run by taking focus from active work.

## Slice 4a: explicit text-acquisition use cases

The Accessibility and clipboard paths first converge in application code, not
in AppKit. `EnqueueCurrentSelection` accepts only a previously captured process
identifier, reads exact text through `SelectedTextReaderPort`, and delegates to
`SelectionEnqueueing` with configured provenance. `EnqueueClipboard` performs
the same orchestration through `ClipboardTextReaderPort`. Neither use case can
choose format, sensitivity, priority, voice, speed, or segmentation policy.

### Falsification

A deliberate orchestration mutant replaced a missing prior PID with `0`,
discarded the Accessibility reader's result in favor of an empty string, and
made clipboard enqueue a no-op. The focused application contract reported six
named assertion failures:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechApplicationTests
# Executed 6 tests, with 6 failures (0 unexpected)
```

The failures exposed the missing typed refusal, unexpected PID `0` read,
unexpected empty selection admission, absent clipboard read, and absent exact
text/source request. All three pre-existing selection/document tests remained
green, so the red result was behavior-specific. The mutant was then removed.

### Green

The final current-selection use case rejects a missing prior process before
calling any reader, passes the exact captured PID to the reader, and passes the
exact returned text to selection admission with configured provenance. The
clipboard use case reads exactly once and delegates the exact string through
the same admission boundary.

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter SpeechApplicationTests
# Executed 6 tests, with 0 failures

python3 ../../scripts/run_with_deadline.py 60 swift test
# Executed 39 tests, with 0 failures
```

## Slice 4b: Accessibility and clipboard readers

`AccessibilitySelectionReader` is an outbound adapter over public macOS
Accessibility APIs. It requests trust only when its explicit read method is
called, queries one known process, and maps permission denial, missing focus,
unsupported selection, empty selection, and other AX failures separately.
`MacClipboardTextReader` asks one pasteboard for its current string and exposes
no write operation.

### Falsification

A deliberate Accessibility mutant suppressed the system prompt option,
discarded successful text, and collapsed all AX outcomes into an empty success.
A deliberate clipboard mutant cleared the owned pasteboard after reading and
treated absent text as an empty success. The focused adapter contract produced
ten behavior-specific failures across all eight executed tests:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter MacTextReadersTests
# Executed 8 tests, with 10 failures (0 unexpected)
```

The output named the `false` versus `true` prompt option, discarded exact text,
four missing typed errors, changed pasteboard counts, and missing no-text
refusal. The mutants were then removed.

### Green

The final Accessibility reader passes `prompt: true` only when explicitly
called, never queries the target after a denied trust check, preserves exact
successful text, rejects whitespace-only selections, and maps every declared
failure separately. The final clipboard reader returns the exact string or a
typed no-text error without changing its pasteboard.

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test --filter MacTextReadersTests
# Executed 8 tests, with 0 failures

python3 ../../scripts/run_with_deadline.py 60 swift test
# Executed 47 tests, with 0 failures
```

## Slice 4c: menu-bar acquisition wiring

The menu-bar presentation now exposes one **Read…** menu containing **Read
Current Selection…**, **Read Clipboard**, and **Read File…**. The selection
action captures the external frontmost process identifier before the popover
becomes key, stores it in `AppState`, and later passes that exact identifier to
`CurrentSelectionEnqueueing`. The clipboard action calls only
`ClipboardEnqueueing`; it neither synthesizes Command-C nor has a pasteboard
write capability.

The medium tests enter through the popover-open sequence and `AppState` action
methods. Their oracle observes event order, the exact captured PID, self-process
rejection, and which application port was called. AppKit host compatibility and
the real Accessibility permission sheet remain large, explicitly coordinated
acceptance checks; these tests do not pretend to prove either.

### Falsification

A deliberate wiring mutant activated the popover before storing the process,
discarded the captured PID when the selection action ran, and made the
clipboard action inert. The focused contract produced four named failures:

```console
python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar --filter WireProtocolTests
# Executed 17 tests, with 4 failures (0 unexpected)
```

The failures reported the exact reversed event order (`observed`, `activated`,
`stored`), `nil` instead of PID `4242`, an unfulfilled clipboard-call
expectation, and a clipboard call count of zero. The self-process refusal and
all pre-existing wire/presentation tests remained green. The mutant was then
removed.

### Green

The final sequence observes, normalizes, and stores the prior process before
running the activation closure. `AppState` snapshots that identifier on the
main actor before dispatching selection acquisition, and each explicit action
delegates to exactly one injected port before refreshing daemon state.

```console
python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar --filter WireProtocolTests
# Executed 17 tests, with 0 failures

python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar
# Executed 51 tests, with 0 failures
```

Both modified design documents also rendered successfully through `mmdc`.
The release bundle builder completed from the working tree, after which
`codesign --verify --deep --strict` and `plutil -lint` both accepted the
generated app. No candidate was installed or launched in this slice, so real
Accessibility trust, selection acquisition, and visible error presentation
remain unclaimed.

## Slice 5a: typed App Intents and bundle metadata

Six `AppIntent` types implement **Read Text**, **Read File**, **Pause**,
**Resume**, **Skip**, and **Set Playback Speed**. Their injected dependency
value contains only the existing selection, document, and speech ports. Read
Text supplies exact literal text with source `macos-intent:text`; Read File
passes an available `IntentFile.fileURL` to document admission; transport maps
to existing commands; playback speed maps the same six UI rates to
`setPlaybackRate`. All intents set `openAppWhenRun` to false.

`AITTSAppShortcuts` supplies six corresponding provider records and phrases.
The release builder uses the active Xcode toolchain to emit constant values and
generate `Contents/Resources/Metadata.appintents`, then validates its semantic
inventory before applying the bundle signature. Apple’s current macOS guidance
clarifies that these provider records do not become preconfigured App Shortcuts
on macOS; the six underlying App Intent actions instead appear while a person
builds a custom shortcut.

### Falsification

A deliberate intent-router mutant discarded Read Text content/provenance,
ignored Read File, admitted a missing file, mapped every transport command to
Pause, and mapped live playback rates to synthesis speed. The catalog test
still passed, while all five behavioral tests failed:

```console
python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar --filter AppIntentsTests
# Executed 6 tests, with 5 failures (0 unexpected)
```

The failures printed the exact bad selection, absent URL, missing typed error,
three Pause commands instead of Pause/Resume/Skip, and six Pause commands
instead of the six expected live playback-rate commands. The mutant was then
removed.

A second deliberate mutant made the package metadata validator accept every
payload. Its exact fixture remained green, while incomplete action, shortcut,
and rate payloads plus a foreground-activating intent all escaped rejection and
failed their tests:

```console
.venv/bin/pytest -q tests/test_distribution.py \
  -k app_intents_metadata_validator
# 1 passed, 4 failed
```

The final validator replaced that mutant.

### Green

The six focused intent tests and all 57 Swift tests pass. The five metadata
validator cases pass, as do the full Python suite and its lint/type gates:

```console
python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar --filter AppIntentsTests
# Executed 6 tests, with 0 failures

python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar
# Executed 57 tests, with 0 failures

uv run ruff check
# All checks passed!

uv run ruff format --check
# 89 files already formatted

uv run mypy
# Success: no issues found in 57 source files

.venv/bin/pytest -q
# complete Python suite passed
```

A clean temporary release bundle then passed the builder's own validator and
`codesign --verify --deep --strict`. Its generated metadata contained exactly:

- action titles: Pause, Read File, Read Text, Resume, Set Playback Speed, Skip;
- shortcut identifiers: the six corresponding Swift intent types;
- playback rates: 0.5×, 0.75×, 1×, 1.5×, 2×, and 3×.

This proves compiler extraction, bundle placement, semantic validation, and
post-metadata signing. The candidate was not installed in this slice, so system
indexing and a real Shortcuts invocation remain unclaimed.

## Slice 5b: installed App Intent indexing

Commit `1b1ff6a` produced a clean signed candidate whose executable SHA-256 was
`9f80f640cc448d08c7051a48f2982dc8b4efee842d5de62dd5f0e8c86fba8b6b`.
The running prior app was terminated by its exact executable path, and its
signed bundle was retained at
`/private/tmp/ai-tts-install-rollback.EoXBxW/AI-TTS.previous.app`. The candidate
then replaced only `~/Applications/AI-TTS.app` and LaunchServices
registered that exact path.

The installed executable retained the candidate SHA-256 and passed
`codesign --verify --deep --strict`. Its `extract.actionsdata` still contained
the exact six action titles, six shortcut identifiers, and six playback rates.
`pbs -dump` continued to resolve both installed Services to the same bundle.

The live `linkd` metadata store was queried read-only after registration. Its
`bundles` table resolved `com.flyingrobots.ai-tts.menubar` to
`~/Applications/AI-TTS.app/`; its `actions` table contained exactly
the six identifiers; and `appShortcuts` contained six rows for the bundle.
This is installed system-indexing evidence, not a claim that a human-visible
Shortcuts journey has run.

Finally, LaunchServices started the menu app with background and hidden flags.
The exact installed process appeared as PID 93872, while `lsappinfo front`
reported the same frontmost application record before and after launch. No
window was opened and no synthetic input was sent. A real Shortcuts invocation
remains the only open App Intent acceptance gate.

The supported `/usr/bin/shortcuts` interface exposed only `run`, `list`,
`view`, and `sign`. A filtered `shortcuts list --show-identifiers` found no
AI-TTS user shortcut, and `shortcuts run PauseSpeechIntent` returned `Couldn't
find shortcut`. Playback remained unheld and the frontmost application record
remained unchanged. This negative receipt establishes that the CLI cannot turn
the generated type identifier into a real invocation by itself; acceptance
requires a user shortcut containing the indexed action.

## Platform-contract correction

Apple’s current
[App Shortcuts platform guidance](https://developer.apple.com/design/human-interface-guidelines/app-shortcuts#macOS)
states that preconfigured App Shortcuts are not supported on macOS. App Intent
actions remain supported as building blocks for custom shortcuts. The observed
six `appShortcuts` rows in `linkd` therefore prove metadata indexing only; they
do not prove six ready-made macOS shortcuts, Siri phrases, or Spotlight
commands.

The installed Xcode 26.6 toolchain was also probed for Apple’s documented
`AppIntentsTesting` module, which can run intents out of process on supported
toolchains. `swiftc -typecheck` failed with `no such module
'AppIntentsTesting'`; no framework or Swift module exists in the installed
macOS SDK. That potentially headless acceptance route is unavailable on this
machine. The remaining supported acceptance boundary is a custom shortcut
created in the foreground Shortcuts editor and then run through
`/usr/bin/shortcuts` or the editor itself.
