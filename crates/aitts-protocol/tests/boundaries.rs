// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: closed daemon envelopes, IPC byte limits, and JSON value kinds.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{
    MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, Request, WireError, decode_event, decode_reply,
    decode_request, encode_request, operation::Operation,
};
use serde_json::{Value, json};

#[test]
fn every_closed_envelope_rejects_an_unknown_field() {
    let requests: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/requests.json")).unwrap();
    for mut request in requests {
        request["unexpected"] = json!({"retained":false});
        assert_eq!(
            decode_request(&serde_json::to_vec(&request).unwrap()),
            Err(WireError::InvalidMessage)
        );
    }
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    for mut record in replies {
        let op: Operation = serde_json::from_value(record["op"].clone()).unwrap();
        record["reply"]["unexpected"] = json!(1);
        assert_eq!(
            decode_reply(op, &serde_json::to_vec(&record["reply"]).unwrap()),
            Err(WireError::InvalidMessage),
            "{op:?}"
        );
    }
    let events: Vec<Value> = serde_json::from_str(include_str!("fixtures/events.json")).unwrap();
    for mut event in events {
        event["unexpected"] = json!(1);
        assert_eq!(
            decode_event(&serde_json::to_vec(&event).unwrap()),
            Err(WireError::InvalidMessage)
        );
    }
}

#[test]
fn required_nullable_reply_fields_cannot_disappear() {
    for reply in [
        json!({"ok":true,"state":null,"held":true}),
        json!({"ok":true,"current":null,"held":true}),
    ] {
        assert!(decode_reply(Operation::Pause, &serde_json::to_vec(&reply).unwrap()).is_err());
    }
    let valid = json!({"ok":true,"state":null,"current":null,"held":true});
    assert!(decode_reply(Operation::Pause, &serde_json::to_vec(&valid).unwrap()).is_ok());
}

#[test]
fn structured_error_codes_round_trip_for_every_operation() {
    for op in Operation::ALL {
        for code in ["bad_request", "not_found", "illegal_state", "internal"] {
            let expected = json!({"ok":false,"error":{"type":code,"message":"Synthetic failure."}});
            let reply = decode_reply(op, &serde_json::to_vec(&expected).unwrap()).unwrap();
            assert_eq!(
                serde_json::from_slice::<Value>(&aitts_protocol::encode_reply(&reply).unwrap())
                    .unwrap(),
                expected
            );
        }
    }
    for invalid in [
        json!({"ok":true,"error":{"type":"bad_request","message":"Synthetic failure."}}),
        json!({"ok":false,"error":{"type":"bad_request","message":"Synthetic failure.","unexpected":1}}),
        json!({"ok":false,"error":{"type":"future","message":"Synthetic failure."}}),
        json!({"ok":false,"error":{"type":"internal"}}),
    ] {
        assert!(decode_reply(Operation::Status, &serde_json::to_vec(&invalid).unwrap()).is_err());
    }
}

#[test]
fn history_boolean_quirk_is_explicit_and_false_is_refused() {
    for op in ["history", "snapshot"] {
        assert!(
            decode_request(&serde_json::to_vec(&json!({"op":op,"limit":true})).unwrap()).is_ok()
        );
        assert!(
            decode_request(&serde_json::to_vec(&json!({"op":op,"limit":false})).unwrap()).is_err()
        );
    }
}

#[test]
fn duplicate_keys_and_impossible_history_events_are_refused() {
    for line in [
        br#"{"op":"submit","text":"first","text":"second"}"#.as_slice(),
        br#"{"op":"status","op":"metrics"}"#,
    ] {
        assert!(decode_request(line).is_err());
    }
    for line in [
        br#"{"event":"history_changed"}"#.as_slice(),
        br#"{"event":"history_changed","removed":"id","cleared":1}"#,
    ] {
        assert!(decode_event(line).is_err());
    }
}

#[test]
fn utf8_escaping_and_encoded_output_count_toward_byte_admission() {
    for token in ["é", "\n", "\\", "\""] {
        let mut text = token.repeat(262_144);
        text.push_str(&"a".repeat(MAX_REQUEST_BYTES));
        let encoded = serde_json::to_vec(&json!({"op":"submit","text":text})).unwrap();
        assert_eq!(decode_request(&encoded), Err(WireError::TooLarge));
    }
    let mut request = decode_request(br#"{"op":"submit","text":"initial"}"#).unwrap();
    if let Request::Submit { text, .. } = &mut request {
        *text = "a".repeat(MAX_REQUEST_BYTES);
    }
    assert_eq!(encode_request(&request), Err(WireError::TooLarge));
    let oversized = vec![b' '; MAX_RESPONSE_BYTES + 1];
    assert_eq!(
        decode_reply(Operation::Status, &oversized),
        Err(WireError::TooLarge)
    );
    assert_eq!(decode_event(&oversized), Err(WireError::TooLarge));
}

#[test]
fn counters_reject_boolean_fractional_negative_and_overflow_numbers() {
    let valid = br#"{"ok":true,"cleared":18446744073709551615}"#;
    let reply = decode_reply(Operation::Clear, valid).unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&aitts_protocol::encode_reply(&reply).unwrap()).unwrap(),
        serde_json::from_slice::<Value>(valid).unwrap()
    );
    for invalid in [
        br#"{"ok":true,"cleared":true}"#.as_slice(),
        br#"{"ok":true,"cleared":1.0}"#,
        br#"{"ok":true,"cleared":-1}"#,
        br#"{"ok":true,"cleared":18446744073709551616}"#,
        br#"{"ok":true,"cleared":1e309}"#,
    ] {
        assert!(decode_reply(Operation::Clear, invalid).is_err());
    }
    assert!(decode_request(b"{\"op\":\"submit\",\"text\":\"\xff\"}").is_err());
}

#[test]
fn nested_known_records_reject_extensions_independently_of_required_fields() {
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    for (operation, pointer) in [
        ("get", "/item"),
        ("status", "/current/active_segment"),
        ("status", "/interruption"),
        ("status", "/engine_preparing"),
        ("snapshot", "/status"),
        ("snapshot", "/runtime"),
        ("snapshot", "/settings"),
        ("engines", "/engines/0"),
        ("engines", "/models/0"),
        ("voice_assignments", "/assignments/0"),
        ("storage", "/entries/0"),
        ("storage", "/receipt"),
        ("metrics", "/queue_depth"),
        ("metrics", "/cache"),
        ("metrics", "/synthesis_wait_ms"),
        ("provenance", "/provenance"),
        ("provenance", "/provenance/clips/0"),
        ("provenance", "/provenance/clips/0/generation/runtime"),
        ("provenance", "/provenance/clips/0/model/runtime"),
        ("provenance", "/provenance/clips/0/model/files/weights.bin"),
    ] {
        let record = replies
            .iter()
            .find(|record| record["op"] == operation)
            .unwrap();
        let op: Operation = serde_json::from_value(record["op"].clone()).unwrap();
        let mut value = record["reply"].clone();
        assert!(decode_reply(op, &serde_json::to_vec(&value).unwrap()).is_ok());
        value
            .pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("unexpected".into(), json!(1));
        assert!(
            decode_reply(op, &serde_json::to_vec(&value).unwrap()).is_err(),
            "{operation} {pointer}"
        );
    }
}
