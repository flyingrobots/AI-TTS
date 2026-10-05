# Selected voice languages and bounded reuse

Change-kind: behavior change.

Settings now offers Voice languages, a multiple-language selection for automatic
agent voice assignments. English is the default and includes American and
British Kokoro voices. The daemon filters the pool before checking unclaimed
voices, then reuses a selected voice when that pool is exhausted. Existing
unpinned assignments outside the selected pool are replaced on the next
admission. Requests for excluded languages are refused before changing a claim.
Explicit listener pins remain authoritative overrides. Already-admitted speech
and the listener's default reading voice retain their previous choices.

The settings API stores a nonempty list of supported language codes as
voice_languages. CLI: ai-tts settings --set voice_languages=en,es. The native
client projects the same field, combines English accents into one option, and
prevents deselecting the last language. Older daemons decode as English by
default. Unknown metadata-free backend catalogs remain usable without invented
language labels; this policy cannot infer a language those engines do not report.

## Assertions and falsification

The narrow regression enters VoiceRegistry with an owned store and a catalog
containing American English, British English, and Spanish. On main 3345ad6,
the third agent received ef_dora and failed the English reuse expectation.
Additional registry/settings tests exercise persisted Spanish selection,
multiple languages, excluded existing claims, pinned overrides, disabled-language
requests, invalid/unavailable selections and whole-request rejection, and a
metadata-free backend. CLI settings persistence is checked against a real owned
daemon socket. Tests name the requested language policy as their oracle.

Seeding an unfiltered pool failed English reuse, selected Spanish, excluded old
claims, and disabled-request assertions. Seeding a forgotten settings write
failed the persistence assertion. Seeds were immediately restored.

Native tests check exact request projection, default/selected snapshot decoding,
and grouping American/British voices into English. Seeding an incorrect wire
field and mapping British voices to Spanish made all three focused tests fail;
restoring the source made all three pass. These are owned-boundary tests, not
proof of interactive checkbox behavior.

## Validation and resources

169 focused Python tests and 173 native tests passed. All Python source/tests
passed Ruff lint/format; all 199 mypy targets passed. The full Python suite first
found an IPC exact-response expectation requiring the new language field and an
offline wheel check whose uv cache had been redirected by the native runner.
The expectation was extended and the existing warm uv cache is now explicitly
selected and included by incremental growth in guarded accounting.

Native validation reused the original checkout's stable .build directory with
two jobs, monitored 20 GiB aggregate build / 4 GiB data / 128 MiB log budgets,
a 6 GiB process-group RSS cap, a 180-second per-process CPU cap, and a 240-second
process-group deadline. The default Swift Build backend exited with SIGXFSZ
under the per-file bound before compilation. SwiftPM's native backend succeeded
under the same limits and target directory. Hosted CI still checks its supported
default backend; the local alternative does not certify that backend.

Raw launch contracts, test logs, and falsification output remain in the original
checkout's .scratch/languages. The stable compiler/cache is intentionally reused,
not a new per-branch cache. Guard monitoring failures and limit breaches terminate
the owned group. Retain logs through integration, then remove owned temporary
stores and redundant task artifacts while preserving the shared compiler cache.
