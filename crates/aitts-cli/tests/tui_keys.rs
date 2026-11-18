// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process).
//! Oracle: the dashboard's invariants. Random key sequences over the recorded
//! snapshots, with random command outcomes and events, never panic; the
//! cursors stay on a row; every request carries `origin: tui`; `dd` cancels
//! only a queued clip; `q` is the only way to quit.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use aitts_cli::tui::{Dashboard, Effect};
use proptest::prelude::*;
use serde_json::{Value, json};

fn snapshots() -> Vec<Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/tui_parity.json"
    );
    let fixture: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    fixture["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .flat_map(|scenario| scenario["snapshots"].as_array().unwrap().clone())
        .collect()
}

#[derive(Clone, Debug)]
enum Step {
    Key(&'static str, u8),
    Snapshot(usize),
    Progress(i64, Option<f64>, bool),
    Disconnect,
    Connect(usize),
    Fail,
}

fn step() -> impl Strategy<Value = Step> {
    let keys = proptest::sample::select(vec![
        "space", "j", "k", "d", "J", "K", "n", "p", "r", "s", "tab", "enter", "x", "",
    ]);
    prop_oneof![
        8 => (keys, 0u8..4).prop_map(|(key, tenths)| Step::Key(key, tenths)),
        1 => any::<usize>().prop_map(Step::Snapshot),
        1 => (any::<i64>(), proptest::option::of(any::<f64>()), any::<bool>())
            .prop_map(|(position, peak, held)| Step::Progress(position, peak, held)),
        1 => Just(Step::Disconnect),
        1 => any::<usize>().prop_map(Step::Connect),
        1 => Just(Step::Fail),
    ]
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(512))]
    #[test]
    fn random_input_keeps_the_dashboard_consistent(steps in proptest::collection::vec(step(), 0..40)) {
        let snapshots = snapshots();
        let pick = |index: usize| snapshots[index % snapshots.len()].clone();
        let mut dashboard = Dashboard::new();
        dashboard.connected(pick(0));
        let mut now = 0.0;
        let mut fail_next = false;
        for step in steps {
            match step {
                Step::Key(key, tenths) => {
                    now += f64::from(tenths) / 10.0;
                    let before = dashboard.screen();
                    match dashboard.key(key, now) {
                        Effect::Command(request) => {
                            prop_assert_eq!(&request["origin"], &json!("tui"));
                            if request["op"] == json!("cancel") {
                                prop_assert_eq!(key, "d");
                                prop_assert_eq!(before.focused, "queue");
                            }
                            let outcome = if fail_next { Err("refused".to_owned()) } else { Ok(pick(3)) };
                            dashboard.command_done(outcome);
                        }
                        Effect::Quit => prop_assert!(false, "{key} quit"),
                        Effect::None => {}
                    }
                }
                Step::Snapshot(index) => dashboard.refresh(pick(index)),
                Step::Progress(position, peak, held) => {
                    let event = json!({"event": "playback_progress", "id": null,
                        "position_ms": position, "audio_peak": peak, "playback_held": held});
                    dashboard.event(&event, &mut || pick(1));
                }
                Step::Disconnect => dashboard.disconnected("gone"),
                Step::Connect(index) => dashboard.connected(pick(index)),
                Step::Fail => fail_next = !fail_next,
            }
            let screen = dashboard.screen();
            prop_assert!(screen.queue.is_empty() || screen.queue_cursor < screen.queue.len());
            prop_assert!(screen.history.is_empty() || screen.history_cursor < screen.history.len());
            prop_assert!(screen.queue.iter().chain(&screen.history).flatten().all(|cell| cell.chars().count() <= 160));
            prop_assert!(!screen.status.is_empty());
        }
        prop_assert_eq!(dashboard.key("q", now), Effect::Quit);
    }
}
