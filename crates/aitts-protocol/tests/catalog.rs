// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: Python catalog projections at committed producer 7b23b96.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{decode_reply, encode_reply, operation::Operation, wire_schema};
use serde_json::{Value, json};

#[test]
fn both_model_catalogs_preserve_null_and_each_adapter_identity_state() {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/catalog-7b23b96.json")).unwrap();
    let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
    let validator =
        jsonschema::validator_for(&serde_json::to_value(wire_schema()).unwrap()).unwrap();
    assert_eq!(
        fixture["installed_models"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["adapter_status"].clone())
            .collect::<Vec<_>>(),
        vec![json!("current"), json!("unknown"), json!("stale")]
    );
    for (op, name) in [
        (Operation::Engines, "engines"),
        (Operation::Snapshot, "snapshot"),
    ] {
        for catalog in ["absent_models", "installed_models"] {
            let mut expected =
                replies.iter().find(|row| row["op"] == name).unwrap()["reply"].clone();
            expected["models"] = fixture[catalog].clone();
            let reply = decode_reply(op, &serde_json::to_vec(&expected).unwrap()).unwrap();
            assert_eq!(
                serde_json::from_slice::<Value>(&encode_reply(&reply).unwrap()).unwrap(),
                expected
            );
            assert!(validator.is_valid(&expected));
        }
    }
}

#[test]
fn adapter_status_rejects_unknown_values_and_preserves_older_absence() {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/catalog-7b23b96.json")).unwrap();
    let mut expected = json!({"ok":true,"engines":[],"models":fixture["absent_models"]});
    let validator =
        jsonschema::validator_for(&serde_json::to_value(wire_schema()).unwrap()).unwrap();
    for invalid in [json!("future"), json!(false), json!(1)] {
        expected["models"][0]["adapter_status"] = invalid;
        assert!(decode_reply(Operation::Engines, &serde_json::to_vec(&expected).unwrap()).is_err());
        assert!(!validator.is_valid(&expected));
    }
    expected["models"][0]
        .as_object_mut()
        .unwrap()
        .remove("adapter_status");
    let reply = decode_reply(Operation::Engines, &serde_json::to_vec(&expected).unwrap()).unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&encode_reply(&reply).unwrap()).unwrap(),
        expected
    );
    assert!(validator.is_valid(&expected));
}
