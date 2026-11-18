// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files and a loopback Unix socket).
//! Conformance suite for the read operations against the Python-written `golden.db`.
//! Oracles: each reply must decode through `aitts_protocol::decode_reply` for its
//! operation (the shared wire contract), and its rows must match `golden.json`, which
//! the Python `Store` read back from the same database.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "test code fails loudly"
)]

mod support;

use std::time::Duration;

use aitts_protocol::error_reply::ErrorCode;
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::value::Nullable;
use aitts_protocol::vocabulary::State;
use serde_json::Value;
use support::{golden, golden_config, request};

fn ask(operation: Operation, line: &str) -> Reply {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let reply = request(&socket, format!("{line}\n").as_bytes());
    assert_eq!(
        daemon.stop(Duration::from_secs(5)),
        aitts_daemon::StopOutcome::Clean
    );
    decode_reply(operation, &reply)
        .unwrap_or_else(|error| panic!("{line} gave {} ({error})", String::from_utf8_lossy(&reply)))
}

fn golden_ids(key: &str) -> Vec<String> {
    golden()[key]
        .as_array()
        .unwrap()
        .iter()
        .map(|id| id.as_str().unwrap().to_owned())
        .collect()
}

fn ids(items: &[aitts_protocol::utterance::Utterance]) -> Vec<String> {
    items.iter().map(|item| item.id.clone()).collect()
}

fn error_code(reply: &Reply) -> ErrorCode {
    match reply {
        Reply::Error(error) => error.error.r#type,
        other => panic!("expected an error reply, got {other:?}"),
    }
}

#[test]
fn list_input_returns_the_python_input_queue_in_order() {
    let Reply::List(items) = ask(Operation::List, r#"{"op":"list","queue":"input"}"#) else {
        panic!("list did not decode as items")
    };
    assert_eq!(ids(&items.items), golden_ids("input"));
}

#[test]
fn list_playback_returns_the_python_playback_queue_in_order() {
    let Reply::List(items) = ask(Operation::List, r#"{"op":"list","queue":"playback"}"#) else {
        panic!("list did not decode as items")
    };
    assert_eq!(ids(&items.items), golden_ids("playback"));
}

#[test]
fn history_returns_terminal_work_newest_first_with_history_fields() {
    let Reply::History(items) = ask(Operation::History, r#"{"op":"history"}"#) else {
        panic!("history did not decode as items")
    };
    assert_eq!(ids(&items.items), golden_ids("history"));
    assert!(items.items.iter().all(|item| !item.final_state.is_absent()));
}

#[test]
fn history_honours_its_limit() {
    let Reply::History(items) = ask(Operation::History, r#"{"op":"history","limit":1}"#) else {
        panic!("history did not decode as items")
    };
    assert_eq!(ids(&items.items), golden_ids("history")[..1].to_vec());
}

#[test]
fn history_refuses_a_zero_limit_as_a_bad_request() {
    let reply = ask(Operation::History, r#"{"op":"history","limit":0}"#);
    assert_eq!(error_code(&reply), ErrorCode::BadRequest);
}

#[test]
fn get_returns_the_stored_utterance() {
    let Reply::Get(item) = ask(Operation::Get, r#"{"op":"get","id":"utt_0001"}"#) else {
        panic!("get did not decode as an item")
    };
    let expected = &golden()["utterances"][0];
    assert_eq!(item.item.id, expected["id"].as_str().unwrap());
    assert_eq!(item.item.text, expected["text"].as_str().unwrap());
    assert_eq!(item.item.state, State::Played);
}

#[test]
fn get_of_an_unknown_id_is_not_found() {
    let reply = ask(Operation::Get, r#"{"op":"get","id":"utt_missing"}"#);
    assert_eq!(error_code(&reply), ErrorCode::NotFound);
}

#[test]
fn status_counts_every_stored_row_by_state() {
    let Reply::Status(status) = ask(Operation::Status, r#"{"op":"status"}"#) else {
        panic!("status did not decode")
    };
    let rows = golden()["utterances"].as_array().unwrap().len();
    let counted: u64 = status.counts.values().sum();
    assert_eq!(counted, u64::try_from(rows).unwrap());
}

#[test]
fn settings_read_reports_the_stored_speed() {
    let Reply::Settings(settings) = ask(Operation::Settings, r#"{"op":"settings"}"#) else {
        panic!("settings did not decode")
    };
    let stored: f64 = golden()["settings"]["speed"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    assert_eq!(settings.settings.speed.as_f64(), Some(stored));
}

#[test]
fn settings_with_an_update_is_refused_because_writes_are_out_of_scope() {
    let reply = ask(
        Operation::Settings,
        r#"{"op":"settings","set":{"speed":1.0}}"#,
    );
    assert_eq!(error_code(&reply), ErrorCode::BadRequest);
}

#[test]
fn voices_reports_the_configured_engine_catalog() {
    let Reply::Voices(voices) = ask(Operation::Voices, r#"{"op":"voices"}"#) else {
        panic!("voices did not decode")
    };
    assert_eq!(voices.voices, ["af_heart", "bm_daniel"]);
}

#[test]
fn metrics_queue_depth_matches_the_python_queues() {
    let Reply::Metrics(metrics) = ask(Operation::Metrics, r#"{"op":"metrics"}"#) else {
        panic!("metrics did not decode")
    };
    let depth = (metrics.queue_depth.input, metrics.queue_depth.playback);
    let expected = (golden_ids("input").len(), golden_ids("playback").len());
    assert_eq!(
        depth,
        (
            u64::try_from(expected.0).unwrap(),
            u64::try_from(expected.1).unwrap()
        )
    );
}

#[test]
fn snapshot_plan_orders_all_unfinished_work_by_queue_order() {
    let Reply::Snapshot(snapshot) = ask(Operation::Snapshot, r#"{"op":"snapshot"}"#) else {
        panic!("snapshot did not decode")
    };
    let utterances = golden()["utterances"].as_array().unwrap().clone();
    let mut unfinished: Vec<&Value> = utterances
        .iter()
        .filter(|row| {
            let id = row["id"].as_str().unwrap().to_owned();
            golden_ids("input").contains(&id) || golden_ids("playback").contains(&id)
        })
        .collect();
    unfinished.sort_by(|a, b| {
        a["order_key"]
            .as_f64()
            .unwrap()
            .total_cmp(&b["order_key"].as_f64().unwrap())
    });
    let expected: Vec<String> = unfinished
        .iter()
        .map(|row| row["id"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(ids(&snapshot.plan), expected);
}

#[test]
fn snapshot_reports_no_current_speech_because_this_daemon_plays_nothing() {
    let Reply::Snapshot(snapshot) = ask(Operation::Snapshot, r#"{"op":"snapshot"}"#) else {
        panic!("snapshot did not decode")
    };
    assert_eq!(snapshot.status.current, Nullable::Null);
}

#[test]
fn an_operation_that_changes_state_is_refused_as_a_bad_request() {
    // `skip` still changes playback outside this daemon's wired operations.
    let reply = ask(Operation::Skip, r#"{"op":"skip"}"#);
    assert_eq!(error_code(&reply), ErrorCode::BadRequest);
}
