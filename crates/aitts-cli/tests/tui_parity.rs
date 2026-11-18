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

use aitts_cli::tui::{Dashboard, Effect, clock_text, format_meter, literal_text};
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

/// Play one scenario as the Python harness does; return (screen, sent).
fn play(scenario: &Value) -> (Value, Vec<Value>) {
    // As the Python scripted client: each read takes the next snapshot, then repeats the last.
    let mut snapshots: Vec<Value> = scenario["snapshots"].as_array().unwrap().clone();
    let mut last = snapshots[0].clone();
    let mut next = move || {
        if !snapshots.is_empty() {
            last = snapshots.remove(0);
        }
        last.clone()
    };
    let mut dashboard = Dashboard::new();
    dashboard.connected(next());
    for event in scenario["events"].as_array().unwrap() {
        dashboard.event(event, &mut next);
    }
    let clock: Vec<f64> = scenario["clock"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t.as_f64().unwrap())
        .collect();
    let mut readings = clock.into_iter();
    let mut sent = Vec::new();
    for key in scenario["keys"].as_array().unwrap() {
        let now = readings.clone().next().unwrap_or(0.0);
        let key = key.as_str().unwrap();
        // The Python clock is read only by d; the frozen readings advance per d press.
        if key == "d" {
            readings.next();
        }
        if let Effect::Command(request) = dashboard.key(key, now) {
            sent.push(request);
            dashboard.command_done(Ok(next()));
        }
    }
    (serde_json::to_value(dashboard.screen()).unwrap(), sent)
}

#[test]
fn each_scenario_shows_and_sends_what_the_python_dashboard_did() {
    let mut failures = Vec::new();
    for scenario in fixture()["scenarios"].as_array().unwrap() {
        let (screen, sent) = play(scenario);
        if numeric(screen.clone()) != numeric(scenario["screen"].clone()) {
            failures.push(format!("{}: showed {screen}", scenario["name"]));
        }
        if sent != *scenario["sent"].as_array().unwrap() {
            failures.push(format!("{}: sent {sent:?}", scenario["name"]));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
