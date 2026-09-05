# Shared MCP caption-setting evidence

Date: 2026-09-05

Change kind: feature

Oracle: the daemon persists one caption preference; the menu UI and MCP read
and write that same value through application ports; setting changes notify the
native event subscriber without changing the five-second liveness watchdog.

## Observed installed state

Before this feature, the installed app was still built from `57a4ab7`, before
the event-driven caption follow-up at `d42a70c`. Reinstalling exact current head
`b7ec327` produced a valid signed app with executable SHA-256
`660e59b1ddc0182f139bad0918b4877747e92a92529dfb012705984bd7b83686`,
launched as PID 76050 without changing the frontmost iTerm2 process. The
persisted `com.flyingrobots.ai-tts.menubar` `captionsEnabled` value was `0`.
That explains why a test performed in that state could not display captions;
it does not establish what the value was during any earlier playback.

## RED: missing shared setting and MCP tools

The new tests were first run against the unfixed implementation. The focused
Python command exited 1 with four named failures:

- MCP inventory lacked `get_caption_settings` and `set_captions_enabled`;
- daemon settings omitted `captions_enabled`;
- a subscribed socket timed out because no settings event was broadcast; and
- CLI `captions_enabled=true` was sent as a string and rejected.

```console
uv run pytest \
  tests/test_mcp_adapter.py::test_mcp_publishes_typed_tool_schemas \
  tests/test_ipc.py::test_settings_get_and_set \
  tests/test_ipc.py::test_caption_setting_change_is_pushed_to_subscribers \
  tests/test_cli.py::test_caption_setting_is_boolean_end_to_end -q
```

The focused Swift command exited 1 at compile time because `Snapshot` had no
`captionsEnabled` member and `SpeechCommand` had no
`setCaptionsEnabled` case:

```console
cd clients/menubar
swift test --filter \
  'UnixSocketSpeechServiceTests|WireProtocolTests.testSnapshotParsesWireShape'
```

## GREEN: typed shared preference

The daemon now stores `captions_enabled` as an exact boolean setting and emits
`settings_changed` after a successful update. The public Python port projects
that wire value through immutable `CaptionSettings` and `SetCaptionsEnabled`
schemas. MCP exposes a read-only `get_caption_settings` tool and an idempotent
`set_captions_enabled` tool. The CLI also projects exact `true`/`false` input
to the boolean wire value.

The Swift application snapshot carries the setting, its socket adapter maps the
same settings operation, and `AppState` applies daemon snapshots. An existing
local `UserDefaults` preference migrates only when the daemon has no explicit
caption value. After that, daemon state is authoritative; event invalidation
pulls the changed snapshot immediately, whether the change came from MCP or the
menu.

Focused Python contracts passed 21 tests. Focused Swift adapter and state
contracts passed 10 tests. The complete Python suite passed 214 tests; the
complete Swift suite passed 59 tests behind its 60-second process-group
deadline. Ruff, Ruff formatting, strict MyPy, and diff hygiene also passed.

## Installed live acceptance

Pending exact-commit rebuild, daemon restart, MCP read/set exercise, and a
user-visible spoken caption check.
