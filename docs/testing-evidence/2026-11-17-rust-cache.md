# Rust cache inventory and full-disk spool — 2026-11-17

Part 5 of issue #136, the last. Agent-written evidence, not human acceptance.
Change kind: feature, plus a refactor: the spool writes through a new
`SpoolStorage` trait (a `File` implements it); the 14 spool tests are unchanged.
`GeneratedStorage.expired` is a retention rule and is out of scope.

## Oracles

- Cache: `crates/aitts-artifacts/tests/fixtures/cache` (`uv run python
  scripts/generate_cache_fixtures.py`). `root/` is a cache with clip directories,
  a legacy `legacy.wav` beside a `legacy/` directory, a `.part` file, a CRLF and
  a 210-character `source.txt`, invalid and truncated UTF-8, and a non-clip file.
  Git does not keep times or links, so `mtimes.json` lists the times, and both
  the script and the test set them and make the three symbolic links. The Python
  `GeneratedStorage.inventory({"held"})` gives `inventory.json`; `remove` on a
  copy gives `removal.json` (counts and remaining members). Compared as JSON.
- Full disk: a byte-vector `SpoolStorage` double with a fixed capacity that fails
  a write past it with `ENOSPC`, as `write(2)` does on a full file system. No
  real disk is filled.

| Test plan item | Test |
|---|---|
| A clip directory that Python wrote is read correctly | `the_inventory_of_a_python_cache_equals_the_python_inventory` |
| Removal matches Python | `removal_counts_equal_the_python_counts`, `removal_leaves_the_python_cache_members` |
| Symbolic link in place of a file or directory | the inventory fixture's three links; `removal_never_follows_a_symbolic_link_out_of_the_cache` |
| Missing cache | `a_missing_cache_root_is_an_empty_inventory` |
| A full disk | `an_append_on_a_full_disk_fails_as_storage_full`, `a_failed_append_delivers_no_unwritten_samples_to_the_reader`, `the_sealed_header_claims_only_the_stored_samples_after_a_full_disk`, `a_full_disk_failure_reaches_the_reader_after_finish` |

## RED to GREEN

Commit `e6d49f3` added 9 tests against stubs (`GeneratedStorage` and
`Spool::with_storage` returned errors): all 9 failed. After the implementation
all 9 passed. Calibration found that the fixture had no links inside a clip
directory or to a legacy WAV, so two links were added to the fixture (Python's
inventory is unchanged; `removal.json` now also lists `alias.wav`).

## Calibration

| Fault | Failing tests |
|---|---|
| No CRLF translation in the preview | inventory |
| Newlines kept in the preview | inventory |
| Preview of 200 characters | inventory |
| Preview from the first 4 bytes | inventory |
| Bytes not summed | inventory |
| Newest time not the maximum | inventory |
| Oldest first | inventory |
| `.part` not protected | inventory, removal counts, removal members |
| Caller protection ignored | inventory, removal counts, removal members |
| Links inside a clip followed | inventory |
| A link to a WAV counted | inventory |
| Legacy WAV not deleted | removal members |
| Protected clips removed | removal counts, removal members |
| Missing root is an error | missing cache |
| Sample count raised before the write | sealed header, failure after finish |

Two faults survived and are recorded: making `remove` follow a directory link
(the inventory never lists a link, so `remove` never reaches it), and skipping
the header write in `with_storage` (the double zero-fills the gap and `seal`
writes the header).

## Repeated runs

10 shuffled runs of `cache` and `spool_full_disk`
(`RUSTC_BOOTSTRAP=1 cargo test -p aitts-artifacts --test cache --test
spool_full_disk -- -Z unstable-options --shuffle`): all passed.
