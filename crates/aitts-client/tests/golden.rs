// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary directories and loopback Unix sockets).
//! Oracle: the concrete conversations captured from the Python daemon at reference
//! 38d967c (`aitts-protocol/tests/fixtures/wire`). A scripted peer replays each
//! captured reply byte for byte; the client must send the captured request and
//! return the reply that `decode_reply` gives for the captured line.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::time::Duration;

use aitts_client::{Client, Delivery, ReconnectPolicy};
use aitts_protocol::{decode_event, decode_reply, decode_request};
use serde_json::Value;
use support::{line, once, transcripts};

const LIMIT: Duration = Duration::from_secs(10);
const NO_RETRY: ReconnectPolicy = ReconnectPolicy {
    delay: Duration::ZERO,
    attempts: 0,
};

#[test]
fn every_captured_request_gets_its_captured_reply() {
    let mut witnesses = 0;
    for (name, records) in transcripts() {
        for record in records
            .iter()
            .filter(|record| record.get("request").is_some())
        {
            if record["request"]["op"] == "subscribe" {
                continue; // The stream test below owns the subscription records.
            }
            let request = decode_request(&line(&record["request"])).unwrap();
            let peer = once(vec![line(&record["reply"])]);
            let reply = Client::new(&peer.socket, LIMIT).request(&request).unwrap();
            let expected = decode_reply(request.operation(), &line(&record["reply"])).unwrap();
            assert_eq!(reply, expected, "{name}: reply");
            let sent: Value = serde_json::from_slice(&peer.received()[0]).unwrap();
            assert_eq!(sent, record["request"], "{name}: request bytes");
            witnesses += 1;
        }
    }
    // 30 records: 9 events, 3 subscribe acknowledgements, and 18 request replies.
    assert_eq!(witnesses, 18);
}

#[test]
fn a_subscription_yields_the_captured_events_in_order() {
    let mut stream = vec![line(&serde_json::json!({"ok": true, "subscribed": true}))];
    let mut expected = Vec::new();
    for (_, records) in transcripts() {
        for event in records.iter().filter_map(|record| record.get("event")) {
            stream.push(line(event));
            expected.push(Delivery::Event(decode_event(&line(event)).unwrap()));
        }
    }
    assert_eq!(expected.len(), 9, "witness count of captured events");
    let peer = once(stream);
    let mut subscription = Client::new(&peer.socket, LIMIT)
        .subscribe(NO_RETRY)
        .unwrap();
    let delivered: Vec<Delivery> = expected
        .iter()
        .map(|_| subscription.next_delivery().unwrap())
        .collect();
    assert_eq!(delivered, expected);
    let sent: Value = serde_json::from_slice(&peer.received()[0]).unwrap();
    assert_eq!(sent, serde_json::json!({"op": "subscribe"}));
}
