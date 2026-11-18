// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; no terminal, socket or clock).
//! Oracle: `tests/fixtures/tui_parity.json`, recorded from the Python
//! `SpeechTUI` (Textual 8.2.8) and its text helpers, which
//! `tests/test_tui_parity_table.py` re-checks under Python 3.12. Each scenario
//! gives the same snapshots, events, keys and clock readings to the Rust
//! dashboard; what it shows and the requests it sends must be the same.
//! Progress values are compared as numbers (Textual stores 0 as 0.0).

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use aitts_cli::tui::{clock_text, format_meter, literal_text};
use serde_json::{Value, json};

fn fixture() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/tui_parity.json"
    );
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

#[test]
fn text_helpers_match_python() {
    let text = &fixture()["text"];
    for pair in text["literal_text"].as_array().unwrap() {
        assert_eq!(literal_text(pair[0].as_str().unwrap()), pair[1], "{pair}");
    }
    for pair in text["clock_text"].as_array().unwrap() {
        assert_eq!(clock_text(pair[0].as_i64()), pair[1], "{pair}");
    }
    for pair in text["format_meter"].as_array().unwrap() {
        assert_eq!(format_meter(pair[0].as_f64()), pair[1], "{pair}");
    }
}

/// Numbers in the progress object compared as numbers.
fn numeric(mut screen: Value) -> Value {
    for key in ["total", "progress"] {
        let value = &screen["progress"][key];
        if let Some(number) = value.as_f64() {
            screen["progress"][key] = json!(number);
        }
    }
    screen
}

#[test]
fn each_scenario_shows_and_sends_what_the_python_dashboard_did() {
    let mut failures = Vec::new();
    for scenario in fixture()["scenarios"].as_array().unwrap() {
        let (dashboard, sent) = support::tui::play(scenario);
        let screen = serde_json::to_value(dashboard.screen()).unwrap();
        if numeric(screen.clone()) != numeric(scenario["screen"].clone()) {
            failures.push(format!("{}: showed {screen}", scenario["name"]));
        }
        if sent != *scenario["sent"].as_array().unwrap() {
            failures.push(format!("{}: sent {sent:?}", scenario["name"]));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
