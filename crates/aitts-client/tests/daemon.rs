// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary files, loopback Unix sockets, daemon threads).
//! The client against the real `aitts-daemon` serving the Python-written
//! `golden.db`. Oracles: `golden.json`, which the Python `Store` read from the
//! same database, and the daemon's own broadcast of a chosen event.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "test code fails loudly"
)]

use std::path::{Path, PathBuf};
use std::time::Duration;

use aitts_client::{Client, ClientError, Delivery, ReconnectPolicy, Subscription};
use aitts_daemon::{Config, EngineView, Running, StopOutcome};
use aitts_protocol::event::Event;
use aitts_protocol::reply::Reply;
use aitts_protocol::vocabulary::ModelState;
use aitts_protocol::{decode_event, decode_request};
use serde_json::Value;

const LIMIT: Duration = Duration::from_secs(10);
const QUIET: Duration = Duration::from_millis(100);

fn store_fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../aitts-store/tests/fixtures")
        .join(name)
}

fn start(dir: &Path) -> Running {
    let database = dir.join("ai-tts.db");
    if !database.exists() {
        std::fs::copy(store_fixture("golden.db"), &database).unwrap();
    }
    aitts_daemon::start(Config {
        socket: dir.join("ai-tts.sock"),
        database,
        cache_dir: dir.join("cache"),
        engine: EngineView {
            name: "kokoro".to_owned(),
            voices: vec!["af_heart".to_owned()],
            is_local: true,
            state: ModelState::Cold,
        },
    })
    .unwrap()
}

fn event() -> Event {
    decode_event(br#"{"event": "model_readiness_changed"}"#).unwrap()
}

/// Broadcast until the subscriber receives it: the daemon registers a
/// subscriber just after its acknowledgement, so one early broadcast may be missed.
fn receive_broadcast(daemon: &Running, subscription: &mut Subscription) -> Delivery {
    for _ in 0..100 {
        daemon.broadcast(&event());
        match subscription.next_delivery() {
            Err(ClientError::TimedOut) => {}
            other => return other.unwrap(),
        }
    }
    panic!("no broadcast arrived in 100 attempts");
}

#[test]
fn list_returns_the_rows_python_read_from_the_same_database() {
    let dir = tempfile::tempdir().unwrap();
    let daemon = start(dir.path());
    let request = decode_request(br#"{"op": "list", "queue": "input"}"#).unwrap();
    let reply = Client::new(daemon.socket(), LIMIT)
        .request(&request)
        .unwrap();
    let golden: Value =
        serde_json::from_str(&std::fs::read_to_string(store_fixture("golden.json")).unwrap())
            .unwrap();
    let Reply::List(items) = reply else {
        panic!("expected a list reply, got {reply:?}")
    };
    let ids: Vec<&str> = items.items.iter().map(|item| item.id.as_str()).collect();
    let expected: Vec<&str> = golden["input"]
        .as_array()
        .unwrap()
        .iter()
        .map(|id| id.as_str().unwrap())
        .collect();
    assert!(!expected.is_empty(), "witness: golden input rows");
    assert_eq!(ids, expected);
    assert_eq!(daemon.stop(Duration::from_secs(5)), StopOutcome::Clean);
}

#[test]
fn a_subscription_connects_again_after_the_daemon_restarts() {
    let dir = tempfile::tempdir().unwrap();
    let first = start(dir.path());
    let socket = first.socket().to_path_buf();
    let policy = ReconnectPolicy {
        delay: Duration::from_millis(10),
        attempts: 50,
    };
    let mut subscription = Client::new(&socket, QUIET).subscribe(policy).unwrap();
    assert_eq!(
        receive_broadcast(&first, &mut subscription),
        Delivery::Event(event())
    );
    assert_eq!(first.stop(Duration::from_secs(5)), StopOutcome::Clean);
    let second = start(dir.path());
    assert_eq!(
        subscription.next_delivery().unwrap(),
        Delivery::Resubscribed
    );
    assert_eq!(
        receive_broadcast(&second, &mut subscription),
        Delivery::Event(event())
    );
    assert_eq!(second.stop(Duration::from_secs(5)), StopOutcome::Clean);
}

#[test]
fn a_subscription_reports_unreachable_when_every_attempt_fails() {
    let dir = tempfile::tempdir().unwrap();
    let daemon = start(dir.path());
    let policy = ReconnectPolicy {
        delay: Duration::from_millis(1),
        attempts: 3,
    };
    let mut subscription = Client::new(daemon.socket(), QUIET)
        .subscribe(policy)
        .unwrap();
    assert_eq!(daemon.stop(Duration::from_secs(5)), StopOutcome::Clean);
    let error = subscription.next_delivery().unwrap_err();
    assert!(matches!(error, ClientError::Unreachable(_)), "{error:?}");
}
