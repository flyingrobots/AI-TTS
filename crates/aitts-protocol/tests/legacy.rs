// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: eight legacy values returned by Python's public provenance operation.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{archive::ArchiveValue, archived_value::ArchivedValue};
use aitts_protocol::{decode_reply, encode_reply, operation::Operation};
use serde_json::{Value, json};

#[test]
fn public_python_provenance_preserves_scalar_array_null_and_false_arguments() {
    let cases: Value =
        serde_json::from_str(include_str!("fixtures/legacy-arguments-aa8d7b3.json")).unwrap();
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    let baseline = &replies
        .iter()
        .find(|record| record["op"] == "provenance")
        .unwrap()["reply"];
    let validator =
        jsonschema::validator_for(&serde_json::to_value(aitts_protocol::wire_schema()).unwrap())
            .unwrap();
    assert_eq!(cases["cases"].as_array().unwrap().len(), 8);
    for case in cases["cases"].as_array().unwrap() {
        let mut expected = baseline.clone();
        expected["provenance"]["arguments"] = case["arguments"].clone();
        expected["provenance"]["origin"] = case["origin"].clone();
        let reply = decode_reply(
            Operation::Provenance,
            &serde_json::to_vec(&expected).unwrap(),
        )
        .unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&encode_reply(&reply).unwrap()).unwrap(),
            expected
        );
        assert!(validator.is_valid(&expected));
    }
}

#[test]
fn only_arguments_gain_value_semantics_and_the_field_remains_required() {
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    let baseline = &replies
        .iter()
        .find(|record| record["op"] == "provenance")
        .unwrap()["reply"];
    let validator =
        jsonschema::validator_for(&serde_json::to_value(aitts_protocol::wire_schema()).unwrap())
            .unwrap();
    for field in ["generation", "model", "audio"] {
        let mut invalid = baseline.clone();
        invalid["provenance"]["clips"][0][field] = json!(["legacy"]);
        assert!(
            decode_reply(
                Operation::Provenance,
                &serde_json::to_vec(&invalid).unwrap()
            )
            .is_err()
        );
        assert!(!validator.is_valid(&invalid));
    }
    let mut missing = baseline.clone();
    missing["provenance"]
        .as_object_mut()
        .unwrap()
        .remove("arguments");
    assert!(
        decode_reply(
            Operation::Provenance,
            &serde_json::to_vec(&missing).unwrap()
        )
        .is_err()
    );
    assert!(!validator.is_valid(&missing));
}

#[test]
fn caller_constructed_historical_values_cannot_bypass_admission() {
    let mut source = ArchiveValue::Array(vec![ArchiveValue::Boolean(false), ArchiveValue::Null]);
    let admitted = ArchivedValue::try_new(&source).unwrap();
    source = ArchiveValue::Text("x".repeat(65_537));
    assert!(ArchivedValue::try_new(&source).is_err());
    assert_eq!(
        serde_json::to_value(admitted).unwrap(),
        json!([false, null])
    );
    for (length, allowed) in [(65_536, true), (65_537, false)] {
        assert_eq!(
            ArchivedValue::try_new(&ArchiveValue::Text("x".repeat(length))).is_ok(),
            allowed
        );
    }
    for (length, allowed) in [(4095, true), (4096, false)] {
        assert_eq!(
            ArchivedValue::try_new(&ArchiveValue::Array(vec![ArchiveValue::Null; length])).is_ok(),
            allowed
        );
    }
    for (depth, allowed) in [(31, true), (32, false)] {
        let mut value = ArchiveValue::Null;
        for _ in 0..depth {
            value = ArchiveValue::Array(vec![value]);
        }
        assert_eq!(ArchivedValue::try_new(&value).is_ok(), allowed);
    }
}
