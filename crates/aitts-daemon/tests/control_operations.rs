// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files and a loopback Unix socket).
//! Conformance suite for the socket operations that change the queue or the hold.
//! Oracles: the Python reference transcripts in `aitts-protocol`'s
//! `fixtures/wire/` (pause, resume: decoded replies must be equal), and for
//! cancel, clear and reorder the Python handlers `_op_cancel`, `_op_clear`,
//! `_op_reorder` and `Store.reorder_pending`, read as the specification. Every
//! reply must decode through `aitts_protocol::decode_reply` for its operation.
//! No audio device: this daemon has no sink, so nothing is played.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use aitts_daemon::{Config, StopOutcome};
use aitts_protocol::error_reply::ErrorCode;
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::vocabulary::State;
use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{Store, SystemClock};
use serde_json::Value;
use support::request;

/// A configuration over a fresh database holding `queued` utterances, plus a
/// played one called `old` when `history` is set.
fn config(dir: &Path, queued: &[&str], history: bool) -> Config {
    let database = dir.join("queue.db");
    let store = Store::open(&database, SystemClock).unwrap();
    let mut ids: Vec<&str> = queued.to_vec();
    if history {
        ids.insert(0, "old");
    }
    for id in ids {
        let new = NewUtterance::new(id.to_owned(), "text".to_owned(), "af_heart".to_owned(), 1.0);
        store.queue().submit(&new).unwrap();
    }
    if history {
        for to in [
            aitts_store::State::Synthesizing,
            aitts_store::State::Ready,
            aitts_store::State::Playing,
            aitts_store::State::Played,
        ] {
            store
                .queue()
                .transition("old", to, &Fields::default())
                .unwrap();
        }
    }
    store.close().unwrap();
    let mut config = support::golden_config(dir);
    std::fs::remove_file(&config.database).unwrap();
    config.database = database;
    config
}

fn ask(socket: &Path, operation: Operation, line: &str) -> Reply {
    let reply = request(socket, format!("{line}\n").as_bytes());
    decode_reply(operation, &reply)
        .unwrap_or_else(|error| panic!("{line} gave {} ({error})", String::from_utf8_lossy(&reply)))
}

fn error_code(reply: &Reply) -> ErrorCode {
    match reply {
        Reply::Error(error) => error.error.r#type,
        other => panic!("expected an error reply, got {other:?}"),
    }
}

/// Queue ids in `list` order.
fn listed(socket: &Path) -> Vec<String> {
    let Reply::List(items) = ask(socket, Operation::List, r#"{"op":"list","queue":"input"}"#)
    else {
        panic!("list failed")
    };
    items.items.into_iter().map(|item| item.id).collect()
}

fn state_of(socket: &Path, id: &str) -> State {
    let Reply::Get(item) = ask(
        socket,
        Operation::Get,
        &format!(r#"{{"op":"get","id":"{id}"}}"#),
    ) else {
        panic!("get {id} failed")
    };
    item.item.state
}

fn stop(daemon: aitts_daemon::Running) {
    assert_eq!(daemon.stop(Duration::from_secs(5)), StopOutcome::Clean);
}

fn transcript(name: &str) -> Vec<Value> {
    let path: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(format!("../aitts-protocol/tests/fixtures/wire/{name}.json"));
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn operation(name: &str) -> Operation {
    match name {
        "pause" => Operation::Pause,
        "resume" => Operation::Resume,
        other => panic!("no operation for {other}"),
    }
}

/// Replay a recorded Python transcript; every decoded reply must be equal.
fn replay(name: &str) {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &[], false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    for entry in transcript(name) {
        let op = operation(entry["request"]["op"].as_str().unwrap());
        let actual = request(&socket, format!("{}\n", entry["request"]).as_bytes());
        let expected = serde_json::to_vec(&entry["reply"]).unwrap();
        assert_eq!(
            decode_reply(op, &actual).unwrap(),
            decode_reply(op, &expected).unwrap(),
            "{name}: {} differs from the Python reply",
            entry["request"]
        );
    }
    stop(daemon);
}

#[test]
fn pause_replies_equal_the_python_transcript() {
    replay("pause");
}

#[test]
fn resume_replies_equal_the_python_transcript() {
    replay("resume");
}

#[test]
fn cancel_of_a_queued_utterance_cancels_it() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &["a"], false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let Reply::Cancel(cancelled) = ask(&socket, Operation::Cancel, r#"{"op":"cancel","id":"a"}"#)
    else {
        panic!("cancel was refused")
    };
    assert_eq!(
        (cancelled.id.as_str(), cancelled.state),
        ("a", State::Cancelled)
    );
    assert_eq!(
        state_of(&socket, "a"),
        State::Cancelled,
        "the store does not show the cancel"
    );
    stop(daemon);
}

#[test]
fn cancel_of_an_unknown_id_is_not_found() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &[], false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    assert_eq!(
        error_code(&ask(
            &socket,
            Operation::Cancel,
            r#"{"op":"cancel","id":"missing"}"#
        )),
        ErrorCode::NotFound
    );
    stop(daemon);
}

#[test]
fn cancel_of_a_history_item_is_illegal_state() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &[], true);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    assert_eq!(
        error_code(&ask(
            &socket,
            Operation::Cancel,
            r#"{"op":"cancel","id":"old"}"#
        )),
        ErrorCode::IllegalState
    );
    stop(daemon);
}

#[test]
fn clear_queue_cancels_pending_work_and_counts_it() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &["a", "b"], true);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let Reply::Clear(cleared) = ask(
        &socket,
        Operation::Clear,
        r#"{"op":"clear","queue":"queue"}"#,
    ) else {
        panic!("clear was refused")
    };
    assert_eq!(cleared.cleared, 2);
    assert_eq!(
        [
            state_of(&socket, "a"),
            state_of(&socket, "b"),
            state_of(&socket, "old")
        ],
        [State::Cancelled, State::Cancelled, State::Played]
    );
    stop(daemon);
}

#[test]
fn reorder_replaces_the_pending_order() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &["a", "b", "c"], false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let Reply::Reorder(reordered) = ask(
        &socket,
        Operation::Reorder,
        r#"{"op":"reorder","ids":["c","a","b"]}"#,
    ) else {
        panic!("reorder was refused")
    };
    assert_eq!(reordered.ids, ["c", "a", "b"]);
    assert_eq!(listed(&socket), ["c", "a", "b"]);
    stop(daemon);
}

#[test]
fn reorder_of_a_partial_plan_is_a_bad_request_and_keeps_order() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &["a", "b"], false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    assert_eq!(
        error_code(&ask(
            &socket,
            Operation::Reorder,
            r#"{"op":"reorder","ids":["b"]}"#
        )),
        ErrorCode::BadRequest
    );
    assert_eq!(listed(&socket), ["a", "b"]);
    stop(daemon);
}

#[test]
fn a_restart_keeps_the_reordered_queue_and_holds_playback() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path(), &["a", "b"], false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config.clone()).unwrap();
    assert!(
        matches!(ask(&socket, Operation::Resume, r#"{"op":"resume"}"#), Reply::Resume(ref t) if !t.held)
    );
    assert!(matches!(
        ask(
            &socket,
            Operation::Reorder,
            r#"{"op":"reorder","ids":["b","a"]}"#
        ),
        Reply::Reorder(_)
    ));
    stop(daemon);
    let daemon = aitts_daemon::start(config).unwrap();
    assert_eq!(listed(&socket), ["b", "a"]);
    // `pause` is the narrowest reply that reports the hold; it was already held.
    let Reply::Pause(transport) = ask(&socket, Operation::Pause, r#"{"op":"pause"}"#) else {
        panic!("pause failed")
    };
    assert!(transport.held);
    let Reply::Resume(transport) = ask(&socket, Operation::Resume, r#"{"op":"resume"}"#) else {
        panic!("resume failed")
    };
    assert!(
        !transport.held,
        "resume after restart did not release the restored hold"
    );
    stop(daemon);
}

#[test]
fn concurrent_clients_cancel_disjoint_work_without_loss() {
    let ids: Vec<String> = (0..8).map(|index| format!("u{index}")).collect();
    let dir = tempfile::tempdir().unwrap();
    let names: Vec<&str> = ids.iter().map(String::as_str).collect();
    let config = config(dir.path(), &names, false);
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    // Any arrival order is legal; the conductor serializes them. The oracle is
    // order-independent: every cancel succeeds and every utterance ends Cancelled.
    thread::scope(|scope| {
        for half in ids.chunks(4) {
            let socket = &socket;
            scope.spawn(move || {
                for id in half {
                    let reply = ask(
                        socket,
                        Operation::Cancel,
                        &format!(r#"{{"op":"cancel","id":"{id}"}}"#),
                    );
                    assert!(
                        matches!(reply, Reply::Cancel(_)),
                        "cancel {id} gave {reply:?}"
                    );
                }
            });
        }
    });
    for id in &ids {
        assert_eq!(state_of(&socket, id), State::Cancelled, "{id}");
    }
    stop(daemon);
}
