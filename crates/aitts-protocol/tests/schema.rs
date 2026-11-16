// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: dispatcher-derived field inventories and captured wire cases.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{
    decode_event, decode_reply, encode_event, encode_reply, operation::Operation, wire_schema,
};
use serde_json::{Value, json};
use std::collections::BTreeSet;

#[test]
fn every_operation_reply_and_emitted_event_has_a_typed_round_trip() {
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    let mut seen = BTreeSet::new();
    for record in replies {
        let operation: Operation = serde_json::from_value(record["op"].clone()).unwrap();
        let expected = &record["reply"];
        let result = decode_reply(operation, &serde_json::to_vec(expected).unwrap()).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&encode_reply(&result).unwrap()).unwrap(),
            *expected
        );
        seen.insert(operation.as_str());
    }
    assert_eq!(
        seen,
        Operation::ALL.into_iter().map(Operation::as_str).collect()
    );
    let events: Vec<Value> = serde_json::from_str(include_str!("fixtures/events.json")).unwrap();
    assert_eq!(events.len(), 14);
    for expected in events {
        let event = decode_event(&serde_json::to_vec(&expected).unwrap()).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&encode_event(&event).unwrap()).unwrap(),
            expected
        );
    }
}

#[test]
fn exported_schema_accepts_the_independent_request_reply_and_event_corpus() {
    let validator =
        jsonschema::validator_for(&serde_json::to_value(wire_schema()).unwrap()).unwrap();
    let mut values: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/requests.json")).unwrap();
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    values.extend(replies.into_iter().map(|record| record["reply"].clone()));
    let events: Vec<Value> = serde_json::from_str(include_str!("fixtures/events.json")).unwrap();
    values.extend(events);
    for value in values {
        assert!(
            validator.is_valid(&value),
            "schema refused corpus value: {value}"
        );
    }
}

#[test]
fn schema_and_codec_reject_unknown_fields_and_wrong_required_kinds() {
    let validator =
        jsonschema::validator_for(&serde_json::to_value(wire_schema()).unwrap()).unwrap();
    for value in [
        json!({"op":"status","future":true}),
        json!({"op":"settings","set":{"captions_enabled":1}}),
        json!({"event":"model_readiness_changed","future":1}),
        json!({"event":"state_changed","id":"fixture","from":null,"to":"Queued","at":"<time>"}),
        json!({"ok":true,"subscribed":false}),
        json!({"ok":false,"error":{"type":"unknown","message":"fixture"}}),
        json!({"event":"history_changed"}),
        json!({"event":"history_changed","removed":"id","cleared":1}),
    ] {
        assert!(!validator.is_valid(&value), "{value}");
        let bytes = serde_json::to_vec(&value).unwrap();
        if value.get("op").is_some() {
            assert!(aitts_protocol::decode_request(&bytes).is_err());
        } else if value.get("event").is_some() {
            assert!(decode_event(&bytes).is_err());
        } else {
            assert!(decode_reply(Operation::Subscribe, &bytes).is_err());
        }
    }
}

#[test]
fn schema_preserves_required_nullables_and_known_metadata_types() {
    let validator =
        jsonschema::validator_for(&serde_json::to_value(wire_schema()).unwrap()).unwrap();
    let valid = json!({"ok":true,"state":null,"current":null,"held":true});
    assert!(validator.is_valid(&valid));
    for invalid in [
        json!({"ok":true,"state":null,"held":true}),
        json!({"ok":true,"current":null,"held":true}),
    ] {
        assert!(!validator.is_valid(&invalid));
    }
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    let mut value = replies
        .into_iter()
        .find(|record| record["op"] == "provenance")
        .unwrap()["reply"]
        .clone();
    value["provenance"]["clips"][0]["model"]["repository"] = json!(false);
    assert!(!validator.is_valid(&value));
    value["provenance"]["clips"][0]["model"]["repository"] = json!("synthetic/repo");
    value["provenance"]["clips"][0]["model"]["new_adapter_field"] = json!({"retained":true});
    assert!(validator.is_valid(&value));
}

#[test]
fn json_schema_and_integer_decoding_have_an_explicit_representation_boundary() {
    let validator =
        jsonschema::validator_for(&serde_json::to_value(wire_schema()).unwrap()).unwrap();
    let value = json!({"op":"history","limit":1.0});
    assert!(validator.is_valid(&value));
    assert!(aitts_protocol::decode_request(&serde_json::to_vec(&value).unwrap()).is_err());
}
