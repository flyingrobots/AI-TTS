// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: captured Python socket conversations, reference 38d967c.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{decode_event, decode_reply, decode_request, encode_event, encode_reply};
use serde_json::Value;

#[test]
fn all_concrete_golden_conversations_round_trip_without_normalizing_values() {
    let fixtures = [
        include_str!("fixtures/wire/submit.json"),
        include_str!("fixtures/wire/status.json"),
        include_str!("fixtures/wire/list.json"),
        include_str!("fixtures/wire/history.json"),
        include_str!("fixtures/wire/pause.json"),
        include_str!("fixtures/wire/resume.json"),
        include_str!("fixtures/wire/skip.json"),
        include_str!("fixtures/wire/settings.json"),
        include_str!("fixtures/wire/subscribe.json"),
    ];
    let mut count = 0;
    for fixture in fixtures {
        let records: Vec<Value> = serde_json::from_str(fixture).unwrap();
        for record in records {
            let encoded = if let Some(request) = record.get("request") {
                let request = decode_request(&serde_json::to_vec(request).unwrap()).unwrap();
                let expected = record.get("reply").unwrap();
                let reply =
                    decode_reply(request.operation(), &serde_json::to_vec(expected).unwrap())
                        .unwrap();
                (encode_reply(&reply).unwrap(), expected)
            } else {
                let expected = record.get("event").unwrap();
                let event = decode_event(&serde_json::to_vec(expected).unwrap()).unwrap();
                (encode_event(&event).unwrap(), expected)
            };
            assert_eq!(
                serde_json::from_slice::<Value>(&encoded.0).unwrap(),
                *encoded.1
            );
            count += 1;
        }
    }
    assert_eq!(count, 30);
}
