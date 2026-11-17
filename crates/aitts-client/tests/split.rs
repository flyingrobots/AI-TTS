// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (loopback Unix sockets). Property: any split of the reply stream
//! into chunks gives the same parsed replies and events as the unsplit stream.
//! Oracle: `decode_reply` and `decode_event` on each whole captured Python line.
//! Proptest prints the failing split and its seed; 32 cases per property.

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
use proptest::prelude::*;
use serde_json::Value;
use support::{line, once, transcripts};

const LIMIT: Duration = Duration::from_secs(10);

fn chunks(bytes: &[u8], cuts: &[usize]) -> Vec<Vec<u8>> {
    let mut points: Vec<usize> = cuts.iter().map(|cut| cut % bytes.len()).collect();
    points.sort_unstable();
    points.dedup();
    let mut pieces = Vec::new();
    let mut start = 0;
    for point in points.into_iter().chain([bytes.len()]) {
        pieces.push(bytes[start..point].to_vec());
        start = point;
    }
    pieces
}

fn replies() -> Vec<(Value, Value)> {
    transcripts()
        .into_iter()
        .flat_map(|(_, records)| records)
        .filter(|record| record.get("request").is_some())
        .map(|record| (record["request"].clone(), record["reply"].clone()))
        .collect()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(32))]

    #[test]
    fn a_split_reply_parses_as_the_whole_reply(
        pick in any::<prop::sample::Index>(),
        cuts in prop::collection::vec(any::<usize>(), 0..12),
    ) {
        let all = replies();
        let (request, reply) = &all[pick.index(all.len())];
        let request = decode_request(&line(request)).unwrap();
        let peer = once(chunks(&line(reply), &cuts));
        let got = Client::new(&peer.socket, LIMIT).request(&request).unwrap();
        prop_assert_eq!(got, decode_reply(request.operation(), &line(reply)).unwrap());
    }

    #[test]
    fn a_split_event_stream_parses_as_the_whole_stream(
        cuts in prop::collection::vec(any::<usize>(), 0..24),
    ) {
        let mut stream = line(&serde_json::json!({"ok": true, "subscribed": true}));
        let mut expected = Vec::new();
        for record in transcripts().into_iter().flat_map(|(_, records)| records) {
            if let Some(event) = record.get("event") {
                stream.extend(line(event));
                expected.push(Delivery::Event(decode_event(&line(event)).unwrap()));
            }
        }
        let peer = once(chunks(&stream, &cuts));
        let policy = ReconnectPolicy { delay: Duration::ZERO, attempts: 0 };
        let mut subscription = Client::new(&peer.socket, LIMIT).subscribe(policy).unwrap();
        for want in expected {
            prop_assert_eq!(subscription.next_delivery().unwrap(), want);
        }
    }
}
