# MCP port-and-adapter test calibration — 2026-09-03

Change kind: feature.

Primary oracle: the approved hexagonal architecture and 100% JSONL MCP
requirements, the public daemon protocol in `docs/design/architecture.md`, and
the MCP 2026-07-28 stdio transport contract.

## Contract cells

| Boundary | Size | Oracle | Controlled dependencies |
|---|---:|---|---|
| Public speech schemas | small | approved public-schema contract | generated values; no I/O |
| Unix-socket mapping | small | daemon NDJSON protocol | owned scripted request client |
| Real socket adapter | medium | daemon protocol and pause semantics | temp state, temp Unix socket, fake engine/sink |
| MCP tools | medium | MCP SDK schema behavior and speech port | in-memory MCP client, owned port fake |
| MCP stdio framing | medium | MCP stdio JSONL specification | owned subprocess and pipes |

## Falsification record

Each mutant was applied alone, its owning test was run once, the named failure
was observed, and the mutant was immediately reverted before the next run.

| Mutant | Command | Observed named failure |
|---|---|---|
| Public schemas changed from `extra="forbid"` to `extra="ignore"` | `uv run pytest tests/test_application_schemas.py::test_public_schema_rejects_unknown_fields -q` | `DID NOT RAISE ValidationError` |
| Enqueue wire operation changed from `submit` to `status` | `uv run pytest tests/test_unix_socket_adapter.py::test_enqueue_encodes_generated_commands_as_json_safe_daemon_requests -q` | generated counterexample reported `status != submit` |
| MCP submission-tool registration removed | `uv run pytest tests/test_mcp_adapter.py::test_mcp_publishes_typed_tool_schemas -q` | inventory reported missing `enqueue_speech` and `requeue_speech` |
| MCP enqueue forced every priority to Normal | `uv run pytest tests/test_mcp_adapter.py::test_mcp_enqueue_maps_flat_arguments_to_the_public_command -q` | public command reported `normal != urgent` |
| MCP entry point printed a banner to stdout | `uv run pytest tests/test_mcp_jsonl.py::test_mcp_stdout_is_only_one_json_object_per_line -q` | `JSONDecodeError` named the non-JSON `AI-TTS MCP` line |
| Unix-socket unreachable error recoded as `transport` | `uv run pytest 'tests/test_unix_socket_adapter.py::test_transport_failures_become_public_service_errors[failure1-unreachable]' -q` | public error assertion reported `transport != unreachable` |

The earlier failed schema-representation assertion is excluded from this
record: it failed because the test searched Python `dict` rendering as though
it were JSON, not because a protected behavior was mutated. The corrected test
reads the schema structure directly.

## Permanent generated evidence

The request schema and Unix-socket encoder use deterministic Hypothesis runs
with shrinking enabled. Any discovered minimized counterexample belongs in the
repository test corpus in the fixing change. No counterexample was found in
this feature run.
