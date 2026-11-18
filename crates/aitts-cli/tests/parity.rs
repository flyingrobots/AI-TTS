// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary directory, loopback Unix socket, one peer thread).
//! Oracle: `tests/fixtures/cli_parity.json`, which `tests/test_cli_parity_table.py`
//! checks against the Python `ai-tts` CLI. For each argument vector the Rust
//! client sends the same request, or refuses with the same exit status and
//! sends nothing.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use serde_json::Value;
use support::{REFUSAL, Recorder, run, same_json};

fn rows() -> Vec<Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/cli_parity.json"
    );
    let table: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    table["rows"].as_array().unwrap().clone()
}

fn argv(row: &Value) -> Vec<&str> {
    row["argv"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a.as_str().unwrap())
        .collect()
}

#[test]
fn each_accepted_row_sends_the_python_request_and_reports_the_daemon_error() {
    let mut failures = Vec::new();
    for row in rows().iter().filter(|row| row.get("request").is_some()) {
        let peer = Recorder::start();
        let outcome = run(&peer.socket, &argv(row));
        let sent = peer.finish();
        let refusal: Value = serde_json::from_str(REFUSAL).unwrap();
        let ok = sent.len() == 1
            && same_json(&sent[0], &row["request"])
            && outcome.status == 1
            && serde_json::from_slice::<Value>(&outcome.stdout).is_ok_and(|out| out == refusal);
        if !ok {
            failures.push(format!(
                "{:?}: sent {sent:?}, exit {}",
                argv(row),
                outcome.status
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "request parity failed:\n{}",
        failures.join("\n")
    );
}

#[test]
fn each_refused_row_exits_like_python_and_sends_nothing() {
    let mut failures = Vec::new();
    for row in rows().iter().filter(|row| row.get("request").is_none()) {
        let peer = Recorder::start();
        let outcome = run(&peer.socket, &argv(row));
        let sent = peer.finish();
        let expected = u8::try_from(row["exit"].as_u64().unwrap()).unwrap();
        if outcome.status != expected || !sent.is_empty() {
            failures.push(format!(
                "{:?}: exit {} (want {expected}), sent {sent:?}",
                argv(row),
                outcome.status
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "refusal parity failed:\n{}",
        failures.join("\n")
    );
}
