// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files). Oracle: the Python store's outcomes and final
//! rows for the same random operation sequences (`sequences.json`, written by
//! `scripts/generate_store_fixtures.py` from the proptest corpus with seed 135).

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use support::sequences::{CASES, generate, replay, to_json};
use support::{dump, expected};

#[test]
fn random_operation_sequences_end_in_the_python_state() {
    let corpus = expected("sequences");
    let cases = corpus.as_array().unwrap();
    let generated = generate();
    assert_eq!(cases.len(), CASES);
    for (number, (ops, case)) in generated.iter().zip(cases).enumerate() {
        let ops_json: Vec<_> = ops.iter().map(to_json).collect();
        assert_eq!(
            serde_json::Value::from(ops_json),
            case["ops"],
            "case {number}: corpus is stale"
        );
        let dir = tempfile::tempdir().unwrap();
        let (store, ids, outcomes) = replay(&dir.path().join("state.db"), ops);
        assert_eq!(
            serde_json::json!(outcomes),
            case["outcomes"],
            "case {number} outcomes"
        );
        assert_eq!(dump(&store, &ids), case["expected"], "case {number} rows");
    }
}
