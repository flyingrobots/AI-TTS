# Rust clip-evidence export — 2026-11-17

Part 3 of issue #136: `aitts_artifacts::evidence::ClipEvidence::export`.
Agent-written evidence, not human acceptance. Change kind: feature. The Python
daemon is unchanged. Writing the evidence records is not in this part.

## Oracle

`crates/aitts-artifacts/tests/fixtures/evidence/python-export.zip` was written by
the Python `ClipEvidence.export` for the evidence cache in `fixtures/evidence/root`
and the item and clips in `request.json`. Regenerate it with
`uv run python scripts/generate_evidence_fixtures.py`. The script pins the export
clock (`1800000000.5`) and replaces `runtime_metadata()` with a fixed value, so the
fixture names no machine. Clip `full` has every evidence file and audio; clip
`legacy` has rotated logs, no source, no generation record, and no audio.

The tests parse both ZIPs. They compare entry names in order, the bytes of the 14
entries other than `manifest.json`, and `manifest.json` as parsed JSON. The raw
ZIP bytes (timestamps, compression) are not the contract and are not compared.

| Acceptance criterion or edge | Test |
|---|---|
| Same entries as the Python export | `the_export_has_the_python_entry_names_in_the_python_order`, `every_entry_except_the_manifest_has_the_python_bytes`, `the_manifest_has_the_python_fields_and_values`, `the_report_lists_the_python_warnings` |
| Owner-only file | `the_archive_is_owner_only` |
| Never overwrite; absolute `.zip` only | `an_existing_destination_is_refused_and_kept`, `a_relative_or_non_zip_destination_is_refused` |
| No partial archive on refusal | `audio_outside_the_root_is_refused_and_leaves_no_archive` |
| Symbolic link in place of a file | `a_symbolic_link_in_place_of_an_evidence_file_is_not_exported`, `a_symbolic_link_in_place_of_the_audio_counts_as_missing` |

## RED to GREEN

Commit `a26d03c` added the fixtures and tests against a stub `export` that
returned an error: 7 of 10 failed. The 3 refusal tests passed against the stub
because it refuses everything; the faults below show they guard their checks.
After the implementation all 10 passed.

## Calibration

One fault at a time in `src/evidence.rs`; source restored and compared after each.

| Fault | Failing tests |
|---|---|
| Rotated synthesis logs in the wrong order | entry order |
| `model.json` not exported | entry order, entry bytes |
| Wrong expected-file set | manifest, warnings |
| No rotation warning | manifest, warnings |
| No legacy `source.txt` | entry order, entry bytes |
| `audio_path` kept in the manifest | manifest |
| No `audio_blake3` | manifest |
| README text changed | entry bytes |
| Export clock ignored | manifest |
| Evidence symbolic links followed | evidence-file link |
| Audio symbolic link followed | audio link |
| No cache-root check | audio outside root |
| Partial archive kept | audio outside root |
| Destination overwritten | existing destination |
| Default file mode | owner-only |
| No `.zip` check | relative or non-zip |

Swapping `playback.previous.jsonl` and `playback.jsonl` survived, because no
fixture clip has both; the synthesis pair (which `legacy` has) was used instead.

## Repeated runs

10 shuffled runs (`RUSTC_BOOTSTRAP=1 cargo test -p aitts-artifacts --test
evidence_export -- -Z unstable-options --shuffle`): all passed.
