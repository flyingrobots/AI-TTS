// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: independent dispatcher inventory at reference 38d967c.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use aitts_protocol::{decode_request, encode_request};
use serde_json::{Value, json};

fn line(value: &Value) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(value).unwrap();
    bytes.push(b'\n');
    bytes
}

fn round_trip(value: &Value) {
    let request = decode_request(&line(value)).unwrap();
    assert_eq!(
        Some(request.operation().as_str()),
        value.get("op").and_then(Value::as_str)
    );
    let encoded = encode_request(&request).unwrap();
    assert_eq!(encoded.last(), Some(&b'\n'));
    assert_eq!(serde_json::from_slice::<Value>(&encoded).unwrap(), *value);
}

#[test]
fn each_dispatch_operation_and_subscription_retains_its_exact_request() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/requests.json")).unwrap();
    assert_eq!(cases.len(), 32);
    for request in cases {
        round_trip(&request);
    }
}

#[test]
fn absence_null_and_explicit_false_remain_distinct() {
    for request in [
        json!({"op":"submit","text":"Reference text."}),
        json!({"op":"submit","text":"Reference text.","source":null,"voice":null,"speed":null,"engine":null}),
        json!({"op":"submit","text":"Reference text.","playback":false,"preempt":false}),
        json!({"op":"rewind"}),
        json!({"op":"rewind","to":null}),
        json!({"op":"settings"}),
        json!({"op":"settings","set":null}),
        json!({"op":"history","before":null}),
        json!({"op":"storage","retention_days":null,"delete":null}),
    ] {
        round_trip(&request);
    }
}

#[test]
fn unknown_fields_and_wrong_known_value_kinds_are_refused() {
    for request in [
        json!({"op":"status","unexpected":true}),
        json!({"op":"submit","text":"Reference text.","playback":1}),
        json!({"op":"submit","text":"Reference text.","content_format":null}),
        json!({"op":"submit","text":"Reference text.","priority":"future"}),
        json!({"op":"settings","set":{"captions_enabled":true,"unexpected":1}}),
        json!({"op":"subscribe","playback_progress":"true"}),
        json!({"op":"no_such_operation"}),
    ] {
        assert!(decode_request(&line(&request)).is_err(), "{request}");
    }
}

#[test]
fn request_limit_counts_the_complete_utf8_line_and_newline() {
    let empty = line(&json!({"op":"submit","text":""}));
    let text = "a".repeat(1_048_576 - empty.len());
    let request = json!({"op":"submit","text":text});
    let boundary = line(&request);
    assert_eq!(boundary.len(), 1_048_576);
    assert!(decode_request(&boundary).is_ok());
    let mut over = boundary.clone();
    over.insert(1, b' ');
    assert!(decode_request(&over).is_err());
    for malformed in [
        b"[]\n".as_slice(),
        b"null\n",
        b"{\"op\":\"status\"}\n{}\n",
        b"{\"op\":\"status\",\"x\":NaN}\n",
        b"{\"op\":\"submit\",\"text\":\"\\ud800\"}\n",
    ] {
        assert!(decode_request(malformed).is_err());
    }
}
