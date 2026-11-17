// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files, loopback Unix sockets, threads).
//! Oracle: `src/aitts/ipc.py` and architecture §5: one owner per socket lease, a
//! 0600 socket, a stale socket replaced, and every failure a typed error reply.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

mod support;

use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::time::{Duration, Instant};

use aitts_daemon::StartError;
use aitts_protocol::error_reply::{ErrorCode, ErrorReply};
use aitts_protocol::event::Event;
use proptest::prelude::*;
use support::{golden_config, json, read_line, request};

const STOP: Duration = Duration::from_secs(5);
const STATUS: &[u8] = b"{\"op\":\"status\"}\n";

fn bad_request(reply: &[u8]) -> bool {
    serde_json::from_slice::<ErrorReply>(reply)
        .is_ok_and(|error| error.error.r#type == ErrorCode::BadRequest)
}

#[test]
fn the_socket_is_private_to_its_owner() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let mode = std::fs::metadata(&socket).unwrap().permissions().mode() & 0o777;
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert_eq!(mode, 0o600, "socket mode was {mode:o}");
}

#[test]
fn a_second_daemon_is_refused_while_the_first_holds_the_lease() {
    let dir = tempfile::tempdir().unwrap();
    let first = aitts_daemon::start(golden_config(dir.path())).unwrap();
    let second = aitts_daemon::start(golden_config(dir.path()));
    assert_eq!(first.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert!(
        matches!(second, Err(StartError::AlreadyRunning)),
        "{second:?}"
    );
}

#[test]
fn the_lease_is_released_when_the_daemon_stops() {
    let dir = tempfile::tempdir().unwrap();
    let first = aitts_daemon::start(golden_config(dir.path())).unwrap();
    assert_eq!(first.stop(STOP), aitts_daemon::StopOutcome::Clean);
    let again = aitts_daemon::start(golden_config(dir.path()));
    assert!(again.is_ok(), "{again:?}");
    assert_eq!(again.unwrap().stop(STOP), aitts_daemon::StopOutcome::Clean);
}

#[test]
fn a_stale_socket_from_a_dead_process_is_replaced() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    drop(UnixListener::bind(&socket).unwrap());
    let daemon = aitts_daemon::start(config).unwrap();
    let reply = request(&socket, STATUS);
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert_eq!(json(&reply)["ok"], true);
}

#[test]
fn a_non_socket_entry_at_the_socket_path_is_refused_and_kept() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    std::fs::write(&config.socket, b"keep me").unwrap();
    let socket = config.socket.clone();
    let started = aitts_daemon::start(config);
    assert!(
        matches!(started, Err(StartError::SocketOccupied)),
        "{started:?}"
    );
    assert_eq!(std::fs::read(socket).unwrap(), b"keep me");
}

#[test]
fn fifty_clients_at_one_time_each_get_their_reply() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let clients: Vec<UnixStream> = (0..50)
        .map(|_| UnixStream::connect(&socket).unwrap())
        .collect();
    for mut client in &clients {
        client.write_all(STATUS).unwrap();
    }
    let answered = clients
        .iter()
        .filter(|client| json(&read_line(client))["ok"] == true)
        .count();
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert_eq!(answered, 50);
}

#[test]
fn a_client_holding_half_a_line_does_not_block_other_clients() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let mut stalled = UnixStream::connect(&socket).unwrap();
    stalled.write_all(b"{\"op\":\"sta").unwrap();
    let reply = request(&socket, STATUS);
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert_eq!(json(&reply)["ok"], true);
}

#[test]
fn half_a_line_at_end_of_input_is_answered_as_one_request() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let mut client = UnixStream::connect(&socket).unwrap();
    client.write_all(b"{\"op\":\"sta").unwrap();
    client.shutdown(std::net::Shutdown::Write).unwrap();
    let reply = read_line(&client);
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert!(bad_request(&reply), "{}", String::from_utf8_lossy(&reply));
}

#[test]
fn an_oversized_request_line_is_refused_as_a_bad_request() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let mut client = UnixStream::connect(&socket).unwrap();
    let oversized = vec![b' '; aitts_protocol::MAX_REQUEST_BYTES + 1];
    // The daemon may close after refusing, before reading the rest.
    let _ = client.write_all(&oversized);
    let reply = read_line(&client);
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert!(bad_request(&reply), "{}", String::from_utf8_lossy(&reply));
}

#[test]
fn a_slow_subscriber_does_not_block_other_subscribers() {
    let dir = tempfile::tempdir().unwrap();
    let config = golden_config(dir.path());
    let socket = config.socket.clone();
    let daemon = aitts_daemon::start(config).unwrap();
    let subscribe = b"{\"op\":\"subscribe\"}\n";
    let slow = UnixStream::connect(&socket).unwrap();
    (&slow).write_all(subscribe).unwrap();
    assert_eq!(json(&read_line(&slow))["subscribed"], true);
    let fast = UnixStream::connect(&socket).unwrap();
    (&fast).write_all(subscribe).unwrap();
    let mut fast = BufReader::new(fast);
    let mut ack = Vec::new();
    fast.read_until(b'\n', &mut ack).unwrap();

    // Far more than a socket buffer and the per-subscriber backlog hold.
    let event: Event = serde_json::from_str(
        r#"{"event":"settings_changed","settings":{"captions_enabled":true}}"#,
    )
    .unwrap();
    let started = Instant::now();
    for _ in 0..20_000 {
        daemon.broadcast(&event);
        let mut line = Vec::new();
        fast.read_until(b'\n', &mut line).unwrap();
        assert!(!line.is_empty(), "the reading subscriber was dropped");
    }
    let elapsed = started.elapsed();
    assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
    assert!(
        elapsed < Duration::from_secs(30),
        "broadcast took {elapsed:?}"
    );
}

proptest! {
    #![proptest_config(ProptestConfig { cases: 64, failure_persistence: None, ..ProptestConfig::default() })]
    #[test]
    fn random_bytes_get_a_typed_error_and_the_daemon_keeps_serving(
        bytes in proptest::collection::vec(any::<u8>().prop_filter("one line", |b| *b != b'\n'), 0..512)
    ) {
        let dir = tempfile::tempdir().unwrap();
        let config = golden_config(dir.path());
        let socket = config.socket.clone();
        let daemon = aitts_daemon::start(config).unwrap();
        let mut line = bytes.clone();
        line.push(b'\n');
        let reply = request(&socket, &line);
        let after = request(&socket, STATUS);
        assert_eq!(daemon.stop(STOP), aitts_daemon::StopOutcome::Clean);
        let is_request = aitts_protocol::decode_request(&line).is_ok();
        prop_assert!(is_request || bad_request(&reply), "input {bytes:?} gave {}", String::from_utf8_lossy(&reply));
        prop_assert_eq!(&json(&after)["ok"], &serde_json::Value::Bool(true));
    }
}
