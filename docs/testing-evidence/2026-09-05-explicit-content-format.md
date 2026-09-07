# Explicit speech content-format evidence

Date: 2026-09-05

Change kind: behavior change

Oracle: content interpretation and length segmentation are independent. Agent
and CLI speech is literal plain text by default; explicitly marked Markdown is
projected through the Markdown AST; `.md` and `.markdown` files select that
projection while other UTF-8 text and extracted PDF text remain literal. Older
raw-socket callers that omit the new field retain their prior automatic
Markdown behavior.

## Boundary decision

`plain_text` and `markdown` are public content formats. The maintained Python
application schema, MCP tool, CLI, Swift application models, selected-file
adapter, and both Unix-socket adapters carry the choice explicitly. The daemon
alone applies the choice before its existing bounded segmentation policy:

- `plain_text` goes directly to length segmentation without Markdown syntax
  removal;
- `markdown` is projected through the existing GitHub-flavored Markdown AST
  and then segmented;
- a missing raw daemon field selects the legacy automatic Markdown behavior;
- an unknown value or an explicitly present JSON `null` is a typed
  `bad_request`.

The stored parent still contains the exact submitted source. Any resulting
child clips still inherit the parent's immutable voice and generation speed.

## RED: daemon interpretation policy

The first daemon contract entered through the real Unix socket and inspected
the resulting durable parent/child plan:

```console
uv run pytest tests/test_ipc.py -q \
  -k 'explicit_plain_text or unknown_content_format or legacy_submit or preserves_markdown'
```

On the unfixed implementation, two tests passed and two failed. Explicit
`plain_text` was still projected as Markdown into a composite child, and the
unknown `ssml` format was accepted. Explicit Markdown and the omitted-field
legacy behavior passed.

After the initial fix, a parameterized invalid-format check exposed a narrower
distinction:

```console
uv run pytest tests/test_ipc.py -q -k rejects_invalid_content_format
# 1 passed, 1 failed
```

`ssml` was rejected, but a present JSON `null` was still treated as if the key
were absent. The parser was changed to test key presence before decoding the
enum. Both invalid cases then passed.

## RED: maintained Python clients

The public-schema, MCP discovery, and two CLI contracts were first run against
the unfixed clients:

```console
uv run pytest \
  tests/test_application_schemas.py::test_enqueue_schema_defaults_agent_speech_to_plain_text \
  tests/test_mcp_adapter.py::test_mcp_publishes_typed_tool_schemas \
  tests/test_cli.py::test_say_defaults_to_literal_plain_text \
  tests/test_cli.py::test_say_can_explicitly_project_markdown -q
# 4 failed
```

The application request had no content-format field, MCP published no such
schema property, CLI default speech was still Markdown-projected, and argparse
rejected `--format markdown`. After the typed field and mappings were added,
all four passed. The generated socket-adapter contract now samples both enum
values across 50 deterministic examples.

## RED: native typed-to-wire mapping

Swift application models and expected requests were updated before the socket
adapter. The focused adapter suite compiled and reported exactly the missing
wire field:

```console
cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 \
  swift test --filter UnixSocketSpeechServiceTests
# 6 tests, 2 failures
```

Both submission cases lacked `content_format`; the other four adapter tests
passed. Adding `submission.contentFormat.rawValue` to the outbound payload made
all six pass.

Three temporary assertion mutants calibrated the rest of the native and
compatibility contract, and each was immediately restored:

- returning one unsegmented clip for explicit plain text failed the long-plain
  transformer contract with 306 words where the oracle requires two clips and
  a largest clip of 180 words;
- mapping a `.md` file to `plainText` failed exactly the Markdown inference
  assertion: 1 failure among 8 local-document tests;
- replacing `document.contentFormat` with `.plainText` in `EnqueueDocument`
  failed its sole application-boundary test;
- defaulting an omitted raw daemon field to `plain_text` failed the sole legacy
  compatibility test because the response ceased to be composite.

With production restored, the combined application, local-document, and socket
suites passed 15 tests.

## Final verification

The restored implementation passed every configured release-candidate gate:

```console
uv run ruff check
# All checks passed!

uv run ruff format --check
# 87 files already formatted

uv run mypy
# Success: no issues found in 57 source files

uv run pytest
# 203 passed

cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test
# 28 tests passed

python3 ../../scripts/run_with_deadline.py 120 \
  swift build -c release --product AITTSMenuBar
# Build of product 'AITTSMenuBar' complete!

cd ../..
uv build --offline
# source distribution and wheel built successfully
```

## Live installed boundary

The pre-refresh daemon was idle, playback was not held, and both pending queues
were empty. It was stopped by exact PID. A shell-background replacement did
not survive the tool shell, so the final daemon was deliberately submitted to
the user's `launchd` domain as `com.flyingrobots.ai-tts`; this is a
session-persistent submitted job, not a newly installed login plist.

The updated daemon is accepting and idle with its prior terminal history
intact. A live raw request with `content_format: null` returned the exact
`bad_request` and left both pending queues empty. The separately built signed
candidate and `~/Applications/AI-TTS.app` executable are
byte-identical at SHA-256
`6f652f7c091175d037bc5f0a57fa5c3c6359a2c25ea8d74807ffae6611726e40`.
`codesign --verify --deep --strict` passed, and the updated menu app launched
against the updated daemon.
