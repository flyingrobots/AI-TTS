// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary directories and loopback Unix sockets).
//! Edge cases of one request. Oracle: issue #131's test plan and the Python
//! client (`src/aitts/client.py`, `cli.py` `EXIT_UNREACHABLE = 2`): an absent
//! daemon, an early close, or silence is unreachable; a bad line is never success.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::time::Duration;

use aitts_client::{Client, ClientError, EXIT_UNREACHABLE};
use aitts_protocol::reply::Reply;
use aitts_protocol::{Request, WireError, decode_request};
use support::{Peer, Script, once};

const LIMIT: Duration = Duration::from_secs(10);

fn status() -> Request {
    decode_request(br#"{"op":"status"}"#).unwrap()
}

#[test]
fn an_absent_socket_is_unreachable_with_exit_status_2() {
    let dir = tempfile::tempdir().unwrap();
    let error = Client::new(dir.path().join("absent.sock"), LIMIT)
        .request(&status())
        .unwrap_err();
    assert!(matches!(error, ClientError::Unreachable(_)), "{error:?}");
    assert_eq!(error.exit_status(), EXIT_UNREACHABLE);
    assert_eq!(EXIT_UNREACHABLE, 2);
}

#[test]
fn a_close_in_the_middle_of_a_reply_is_reported_as_closed() {
    let peer = once(vec![br#"{"ok": true, "subscr"#.to_vec()]);
    let error = Client::new(&peer.socket, LIMIT)
        .request(&status())
        .unwrap_err();
    assert_eq!(error, ClientError::Closed);
    assert_eq!(error.exit_status(), EXIT_UNREACHABLE);
}

#[test]
fn a_reply_that_is_not_json_is_an_error_not_success() {
    let peer = once(vec![b"{\"ok\": true,\n".to_vec()]);
    let error = Client::new(&peer.socket, LIMIT)
        .request(&status())
        .unwrap_err();
    assert_eq!(error, ClientError::Wire(WireError::InvalidMessage));
}

#[test]
fn a_silent_daemon_times_out() {
    let peer = Peer::serve(vec![Script {
        chunks: Vec::new(),
        hold: true,
    }]);
    let error = Client::new(&peer.socket, Duration::from_millis(200))
        .request(&status())
        .unwrap_err();
    assert_eq!(error, ClientError::TimedOut);
    drop(peer);
}

#[test]
fn a_reply_larger_than_one_read_is_decoded_whole() {
    // 1 MiB of message text: many socket reads on any platform buffer size.
    let message = "x".repeat(1 << 20);
    let reply = serde_json::json!({"ok": false, "error": {"type": "internal", "message": message}});
    let peer = once(vec![support::line(&reply)]);
    match Client::new(&peer.socket, LIMIT).request(&status()).unwrap() {
        Reply::Error(error) => assert_eq!(error.error.message.len(), 1 << 20),
        other => panic!("expected the error reply, got {other:?}"),
    }
}

#[test]
fn a_line_over_the_response_limit_is_refused() {
    let oversized = vec![b' '; aitts_protocol::MAX_RESPONSE_BYTES + 1];
    let peer = once(vec![oversized]);
    let error = Client::new(&peer.socket, LIMIT)
        .request(&status())
        .unwrap_err();
    assert_eq!(error, ClientError::Wire(WireError::TooLarge));
}
