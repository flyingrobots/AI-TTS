// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Replays a recorded dashboard scenario as the Python harness did.

#![allow(dead_code, reason = "each test binary uses a different subset")]
#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use aitts_cli::tui::{Dashboard, Effect};
use serde_json::Value;

pub(crate) fn fixture() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/tui_parity.json"
    );
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

pub(crate) fn scenario(name: &str) -> Value {
    fixture()["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .find(|scenario| scenario["name"] == name)
        .unwrap()
        .clone()
}

/// Play one scenario; return the dashboard and the requests it sent.
pub(crate) fn play(scenario: &Value) -> (Dashboard, Vec<Value>) {
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
    (dashboard, sent)
}
