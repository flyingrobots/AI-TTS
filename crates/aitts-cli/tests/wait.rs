// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary directory, loopback Unix socket, one peer thread).
//! Oracle: `aitts.cli` and `Client.wait_for_terminal` in the Python CLI and
//! `docs/design/features.md` section 8: `wait` and `say --wait` subscribe
//! before they read the current state, exit 0 only for `Played`, exit 3 for
//! another terminal state, and exit 2 when the deadline passes. Replies are the
//! captured Python daemon replies in `aitts-protocol/tests/fixtures/wire`, and
//! the protocol `get` reply fixture.
//! Ordering is forced by the peer: it writes events only after it has answered
//! the `get`, so no test depends on timing.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "test code fails loudly"
)]

mod support;

use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::thread::JoinHandle;

use serde_json::{Value, json};
use support::run;

const ID: &str = "utt_0001";

fn wire(name: &str) -> Vec<Value> {
    let path = format!(
        "{}/../aitts-protocol/tests/fixtures/wire/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

/// The captured reply to the first request with operation `op` in `name`.
fn captured(name: &str, op: &str) -> Value {
    wire(name)
        .into_iter()
        .find(|record| record["request"]["op"] == json!(op))
        .map(|record| record["reply"].clone())
        .unwrap()
}

/// A captured submit reply for speech accepted while playback is held.
fn held_submit() -> Value {
    let mut reply = captured("submit.json", "submit");
    assert_eq!(reply["playback_held"], json!(true), "witness: held queue");
    reply["id"] = json!(ID);
    reply
}

/// The fixture `get` reply (`aitts-protocol/tests/fixtures/replies.json`) for
/// utterance `ID` in `state`.
fn item(state: &str) -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../aitts-protocol/tests/fixtures/replies.json"
    );
    let replies: Vec<Value> = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let mut reply = replies
        .into_iter()
        .find(|record| record["op"] == json!("get"))
        .map(|record| record["reply"].clone())
        .unwrap();
    reply["item"]["id"] = json!(ID);
    reply["item"]["state"] = json!(state);
    reply
}

fn changed(id: &str, to: &str) -> Value {
    json!({"event": "state_changed", "id": id, "from": "Queued", "to": to, "at": 1.0})
}

/// A peer that answers one connection per reply, in order, keeps every
/// connection open, then writes `events` on the subscription connection.
struct Peer {
    socket: std::path::PathBuf,
    _dir: tempfile::TempDir,
    handle: JoinHandle<Vec<Value>>,
}

fn serve(replies: Vec<Value>, events: Vec<Value>) -> Peer {
    let dir = tempfile::tempdir().unwrap();
    let socket = dir.path().join("peer.sock");
    let listener = UnixListener::bind(&socket).unwrap();
    let handle = std::thread::spawn(move || {
        let mut requests = Vec::new();
        let mut open: Vec<UnixStream> = Vec::new();
        for reply in replies {
            let (stream, _) = listener.accept().unwrap();
            let mut line = Vec::new();
            BufReader::new(&stream)
                .read_until(b'\n', &mut line)
                .unwrap();
            requests.push(serde_json::from_slice::<Value>(&line).unwrap());
            (&stream)
                .write_all(format!("{reply}\n").as_bytes())
                .unwrap();
            open.push(stream);
        }
        let subscribed = requests.iter().position(|r| r["op"] == json!("subscribe"));
        if let Some(index) = subscribed {
            for event in events {
                // The client may already have finished; its close is not a test failure.
                let _ = (&open[index]).write_all(format!("{event}\n").as_bytes());
            }
        }
        for stream in &open {
            let _ = (&*stream).read_to_end(&mut Vec::new());
        }
        requests
    });
    Peer {
        socket,
        _dir: dir,
        handle,
    }
}

fn subscribed() -> Value {
    json!({"ok": true, "subscribed": true})
}

fn ops(requests: &[Value]) -> Vec<String> {
    requests
        .iter()
        .map(|r| r["op"].as_str().unwrap().to_owned())
        .collect()
}

#[test]
fn wait_exits_zero_when_the_utterance_is_played() {
    let peer = serve(
        vec![subscribed(), item("Queued")],
        vec![changed(ID, "Played")],
    );
    let outcome = run(&peer.socket, &["wait", ID]);
    assert_eq!(outcome.status, 0);
    assert_eq!(
        outcome.json(),
        json!({"ok": true, "id": ID, "final_state": "Played"})
    );
    let requests = peer.handle.join().unwrap();
    assert_eq!(
        ops(&requests),
        ["subscribe", "get"],
        "subscribe before reading state"
    );
    assert_eq!(requests[1], json!({"op": "get", "id": ID}));
}

#[test]
fn wait_exits_three_for_each_terminal_state_except_played() {
    for state in ["Skipped", "Cancelled", "Failed"] {
        let peer = serve(vec![subscribed(), item("Queued")], vec![changed(ID, state)]);
        let outcome = run(&peer.socket, &["wait", ID]);
        assert_eq!(outcome.status, 3, "{state}");
        assert_eq!(outcome.json()["final_state"], json!(state));
        peer.handle.join().unwrap();
    }
}

#[test]
fn wait_ignores_events_for_other_utterances_and_non_terminal_states() {
    let events = vec![
        changed("utt_other", "Played"),
        changed(ID, "Playing"),
        json!({"event": "history_changed"}),
        changed(ID, "Failed"),
    ];
    let peer = serve(vec![subscribed(), item("Queued")], events);
    let outcome = run(&peer.socket, &["wait", ID]);
    assert_eq!(outcome.status, 3);
    assert_eq!(outcome.json()["final_state"], json!("Failed"));
    peer.handle.join().unwrap();
}

#[test]
fn wait_returns_a_state_that_is_already_terminal_without_an_event() {
    let peer = serve(vec![subscribed(), item("Played")], vec![]);
    let outcome = run(&peer.socket, &["wait", ID]);
    assert_eq!(outcome.status, 0);
    assert_eq!(outcome.json()["final_state"], json!("Played"));
    peer.handle.join().unwrap();
}

#[test]
fn wait_past_its_deadline_exits_two_as_unreachable() {
    let peer = serve(vec![subscribed(), item("Queued")], vec![]);
    let outcome = run(&peer.socket, &["wait", ID, "--timeout", "0"]);
    assert_eq!(outcome.status, 2);
    assert_eq!(outcome.json()["error"]["type"], json!("unreachable"));
    peer.handle.join().unwrap();
}

#[test]
fn wait_for_an_unknown_id_reports_the_daemon_error() {
    let missing = json!({"ok": false, "error": {"type": "not_found", "message": "no"}});
    let peer = serve(vec![subscribed(), missing.clone()], vec![]);
    // The deadline only bounds a broken client, which would otherwise wait forever.
    let outcome = run(&peer.socket, &["wait", ID, "--timeout", "5"]);
    assert_eq!(outcome.status, 1);
    assert_eq!(outcome.json(), missing);
    peer.handle.join().unwrap();
}

#[test]
fn say_wait_in_a_held_queue_reports_the_submit_reply_and_final_state() {
    for (state, status) in [("Played", 0), ("Cancelled", 3)] {
        let submit = held_submit();
        let peer = serve(
            vec![submit.clone(), subscribed(), item("Queued")],
            vec![changed(ID, state)],
        );
        let outcome = run(&peer.socket, &["say", "hi", "--wait"]);
        assert_eq!(outcome.status, status, "{state}");
        let mut expected = submit;
        expected["final_state"] = json!(state);
        assert_eq!(outcome.json(), expected);
        let requests = peer.handle.join().unwrap();
        assert_eq!(ops(&requests), ["submit", "subscribe", "get"]);
    }
}
