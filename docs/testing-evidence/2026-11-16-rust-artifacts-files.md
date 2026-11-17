# Rust artifacts: private files and atomic publication — 2026-11-16

This record covers the first part of issue #136, the new `aitts-artifacts` crate.
It is agent-written evidence, not human acceptance. Change kind: feature. The
Python daemon is unchanged.

## Oracles

- `aitts.adapters.private_files` and `tests/test_private_state_permissions.py`:
  modes 0700 and 0600, narrowing of existing paths, symbolic-link refusal, FIFO
  refusal without blocking, exclusive creation.
- `aitts.adapters.audio_artifacts` and `tests/test_audio_artifacts.py`: the
  `<id>/.<id>.wav.part` candidate and `<id>/<id>.wav` published paths, crash
  sweep, identity checks, and the usable-file rule.

All 11 tests are small: one temporary directory each, no network, no clock.

| Acceptance criterion (#136) | Test |
|---|---|
| Owner-only files and directories | `new_directories_and_files_are_owner_only`, `existing_permissive_paths_are_narrowed`, `candidate_and_published_paths_use_the_python_layout` |
| A file is published atomically | `a_partial_write_is_never_visible_at_the_published_path`, `candidate_and_published_paths_use_the_python_layout` |
| Edge: symbolic link in place of a file | `a_symbolic_link_in_place_of_a_file_or_directory_is_refused`, `prepare_leaves_symbolic_links_and_their_targets_alone` |
| Failure mode: crash between write and rename | `prepare_discards_crash_candidates_and_keeps_published_audio` |

Not covered here: the Python clip-directory read, the evidence ZIP export, the
spool property test, and the full-disk edge. They belong to the spool, evidence
and cache modules of the same issue.

## RED to GREEN

The audio tests were written against an `AudioArtifacts` whose operations
returned an error. `cargo test -p aitts-artifacts` failed all 6. After the
implementation, all 6 passed. The `private_fs` module was written before its
tests, so its 5 tests passed from the start; the faults below calibrate them.

## Assertion calibration

One fault at a time was applied to the production source, the named test binary
was run, and the source bytes were restored and compared.

| Fault | Detected by |
|---|---|
| No `O_NOFOLLOW` | `a_symbolic_link_in_place_of_a_file_or_directory_is_refused` |
| No `O_NONBLOCK` | `a_fifo_in_place_of_a_file_is_refused_without_blocking` (5 s bound) |
| File mode 0644 | `new_directories_and_files_are_owner_only`, `existing_permissive_paths_are_narrowed` |
| Existing directory not narrowed | `existing_permissive_paths_are_narrowed` |
| No regular-file check | `a_fifo_in_place_of_a_file_is_refused_without_blocking` |
| Creation not exclusive | `create_refuses_an_existing_file` |
| Publish copies, not renames | `candidate_and_published_paths_use_the_python_layout` |
| Nested crash candidate kept | `prepare_discards_crash_candidates_and_keeps_published_audio` |
| No candidate identity check | `identities_that_escape_the_root_are_refused` |
| Empty file usable | `only_a_non_empty_regular_file_is_usable` |

The first FIFO test had no time bound, so the `O_NONBLOCK` fault hung instead
of failing; the test now runs the call on a thread with a 5 s limit. The first
identity test survived the candidate-check fault, because the rename failed on
a missing directory; the test now creates the other directory first.
