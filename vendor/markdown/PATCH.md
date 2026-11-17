# Locally modified Markdown parser

This directory contains a modified subset of `markdown` 1.0.0 (`markdown-rs`).
It is not a pristine upstream release. AI-TTS uses this path dependency to admit
parser resources before growth while retaining the existing speech corpus.
The original unbounded `to_mdast`, `to_html`, and options remain available.

## Upstream identity and retained files

- Package: `markdown`, version `1.0.0`.
- Archive: <https://static.crates.io/crates/markdown/markdown-1.0.0.crate>.
- Archive SHA-256: `a5cab8f2cadc416a82d2e783a1946388b31654d391d1c7d92cc1f03e295b1deb`.
- License: upstream MIT notice retained unchanged in [license](license).
- Retained subset: `src/`, `Cargo.toml`, `Cargo.toml.orig`, and `license`.
- [UPSTREAM-SHA256SUMS](UPSTREAM-SHA256SUMS) records each retained original file.
- [local.patch](local.patch) is the complete patch against those originals.
- [MODIFIED-SHA256SUMS](MODIFIED-SHA256SUMS) records the modified subset and patch.

The archive checksum identifies the published crate; the file manifests identify
exactly which files are retained. No dependency update is implied by this patch.

## Local behavior

`to_mdast_bounded` creates one budget for the complete parse and AST construction.
The AI-TTS domain facade supplies its hard ceilings and can request lower limits.
The budget follows child tokenizers, edit maps, and temporary AST buffers.

Semantic changes are concentrated in these boundaries:

- `limits.rs` defines typed refusals and cumulative node/event/work accounting.
- `tokenizer.rs` checks before each event enters a vector and before grammar steps.
- `construct/document.rs` checks recognized container depth and a separate scratch
  slot before growth. Container exits can now return resource errors.
- `util/edit_map.rs` checks new event arrays and edit records before allocation.
  It charges scans, sorting, link adjustment, and event moves.
- `construct/attention.rs` charges backward opener searches and stack copies.
  Resolver event stacks also have a depth limit.
- `subtokenize.rs` shares the budget and charges child-event scans.
- `to_mdast.rs` checks root, child, and temporary-buffer admission before construction.
  The depth cap also bounds recursive tree access and drop during an error.

Most construct-file edits are mechanical propagation of the newly fallible event
and resolver operations. `state_try!` returns the ordinary `State::Error`; it does
not panic, suppress an error, or continue after a failed push. Resolver loops use
the same work counter. Existing unbounded entrypoints pass no budget and preserve
the original operations and options.

The bounded entrypoint rejects MDX callbacks/constructs and GFM bare-link recognition.
The domain does not enable these options. This avoids promising bounded behavior
for arbitrary external callbacks or unused extension paths.

## Accounting boundaries

Events and edit records count **cumulative admissions**, including records later
merged or discarded. They are not peak live records. Moving already admitted
records does not spend another event admission; allocating new records does.
The event cap bounds supporting indexes and buffers derived from these records.
The byte ceiling independently bounds source slices and plain-text word vectors.
AST node count and depth separately bound the recursive result and its adaptation.

On the pinned 64-bit toolchain, an event occupies 80 bytes, an edit tuple 40 bytes,
a vector header 24 bytes, a parser point 32 bytes, and an AST node 152 bytes.
During an edit-map application, retained source capacities, split slices, edit
vectors, and the output reserve can coexist. A conservative event/edit storage
allowance is `(6E + 16) * 80 + 2E * 40 + (3E + 1) * 24` bytes, where `E` is the
cumulative admission ceiling. The terms cover event backing buffers, edit tuple
capacity, and jump/slice-vector headers. At the domain default `E = 4,194,304`,
this allowance is about 2.47 GiB. This is a source-level component accounting
allowance, not a total process-RSS limit or an allocator-byte meter: AST values,
strings, attention-stack copies, allocator metadata, and runtime state are separate.
Caller execution and memory guards remain necessary. Measured RSS and timing
belong in the dated validation record, not this component allowance.

Work counts charged parser actions and scans, not CPU instructions or time.
The limits do not claim a hard wall-time deadline. Error cleanup drops only the
admitted structures; the bounded AST depth prevents an unbounded recursive drop.

## Verify and update

From the repository root, run:

```sh
python3 scripts/check_markdown_vendor.py
cargo fmt --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

The vendor check hashes all retained files, reverses the local patch in an owned
temporary directory, and verifies every reconstructed upstream file. Rust CI runs
that check. `cargo fmt --check` checks workspace members; `--all` would also rewrite
the vendored upstream dependency with this project's formatting style. Local patch
files retain the upstream Rust 2018 style and are reviewed through `local.patch`.

An upstream update requires a new archive checksum, original-file manifest, complete
local patch, and modified-file manifest. Re-run the unchanged speech corpus, bounded
resource controls, upstream unit tests, and comparisons of the unbounded APIs.
Review every semantic budget check again when upstream changes its allocation paths.

## Changed paths

- `src/construct/attention.rs`
- `src/construct/autolink.rs`
- `src/construct/block_quote.rs`
- `src/construct/character_escape.rs`
- `src/construct/character_reference.rs`
- `src/construct/code_indented.rs`
- `src/construct/content.rs`
- `src/construct/definition.rs`
- `src/construct/document.rs`
- `src/construct/flow.rs`
- `src/construct/frontmatter.rs`
- `src/construct/gfm_autolink_literal.rs`
- `src/construct/gfm_footnote_definition.rs`
- `src/construct/gfm_label_start_footnote.rs`
- `src/construct/gfm_table.rs`
- `src/construct/gfm_task_list_item_check.rs`
- `src/construct/hard_break_escape.rs`
- `src/construct/heading_atx.rs`
- `src/construct/heading_setext.rs`
- `src/construct/html_flow.rs`
- `src/construct/html_text.rs`
- `src/construct/label_end.rs`
- `src/construct/label_start_image.rs`
- `src/construct/label_start_link.rs`
- `src/construct/list_item.rs`
- `src/construct/mdx_esm.rs`
- `src/construct/paragraph.rs`
- `src/construct/partial_bom.rs`
- `src/construct/partial_data.rs`
- `src/construct/partial_destination.rs`
- `src/construct/partial_label.rs`
- `src/construct/partial_mdx_expression.rs`
- `src/construct/partial_mdx_jsx.rs`
- `src/construct/partial_non_lazy_continuation.rs`
- `src/construct/partial_space_or_tab.rs`
- `src/construct/partial_space_or_tab_eol.rs`
- `src/construct/partial_title.rs`
- `src/construct/partial_whitespace.rs`
- `src/construct/raw_flow.rs`
- `src/construct/raw_text.rs`
- `src/construct/string.rs`
- `src/construct/text.rs`
- `src/construct/thematic_break.rs`
- `src/lib.rs`
- `src/limits.rs`
- `src/parser.rs`
- `src/resolve.rs`
- `src/subtokenize.rs`
- `src/to_mdast.rs`
- `src/tokenizer.rs`
- `src/util/edit_map.rs`
