// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Write `tests/fixtures/sequences.ops.json`, the random operation sequences that
//! `scripts/generate_store_fixtures.py` replays through the Python store.
//!
//! Run: `cargo run -p aitts-store --example write_sequences`.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "a fixture tool fails loudly"
)]

#[path = "../tests/support/sequences.rs"]
#[allow(
    dead_code,
    reason = "the example writes the corpus but does not replay it"
)]
mod sequences;

use std::path::Path;

fn main() {
    let cases: Vec<serde_json::Value> = sequences::generate()
        .iter()
        .map(|ops| ops.iter().map(sequences::to_json).collect())
        .collect();
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/sequences.ops.json");
    let text = serde_json::to_string_pretty(&cases).unwrap();
    std::fs::write(path, text + "\n").unwrap();
}
