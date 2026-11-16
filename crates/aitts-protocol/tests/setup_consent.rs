// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: code-only setup consent must survive the wire unchanged.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use aitts_protocol::{decode_request, encode_request};
use serde_json::{Value, json};

#[test]
fn code_only_setup_preserves_omitted_false_and_true() {
    let schema = serde_json::to_value(aitts_protocol::wire_schema()).unwrap();
    let validator = jsonschema::validator_for(&schema).unwrap();
    for expected in [
        json!({"op":"model_setup","name":"kokoro"}),
        json!({"op":"model_setup","name":"kokoro","refresh_only":false}),
        json!({"op":"model_setup","name":"kokoro","refresh_only":true}),
    ] {
        let request = decode_request(&serde_json::to_vec(&expected).unwrap()).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&encode_request(&request).unwrap()).unwrap(),
            expected
        );
        assert!(validator.is_valid(&expected));
    }
}

#[test]
fn code_only_setup_rejects_null_and_wrong_value_kinds() {
    let schema = serde_json::to_value(aitts_protocol::wire_schema()).unwrap();
    let validator = jsonschema::validator_for(&schema).unwrap();
    for value in [
        Value::Null,
        json!(0),
        json!(1),
        json!("true"),
        json!([]),
        json!({}),
    ] {
        let invalid = json!({"op":"model_setup","name":"kokoro","refresh_only":value});
        assert!(decode_request(&serde_json::to_vec(&invalid).unwrap()).is_err());
        assert!(!validator.is_valid(&invalid));
    }
}
