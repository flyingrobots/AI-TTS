// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: daemon provenance returns saved metadata verbatim.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{decode_reply, encode_reply, operation::Operation};
use serde_json::{Value, json};

fn provenance(arguments: &Value, model: &Value) -> Value {
    json!({"ok":true,"provenance":{
        "origin":"Synthetic caller","caller_source":null,"arguments":arguments,
        "source_blake3":"source-digest","resolved_voice":"bm_daniel","resolved_speed":1.0,
        "replay_of":null,"submitted_at":1_700_000_000.25,
        "clips":[{"artifact_id":"utt_fixture","generation":null,"audio":null,"model":model}]
    }})
}

#[test]
fn archival_objects_preserve_legacy_extensions_with_typed_known_metadata() {
    let expected = provenance(
        &json!({"legacy_flag":{"nested":[true,null,1,1.5,"<id:1>"]},"voice":"bm_daniel"}),
        &json!({"repository":"reference/model","adapter_extension":{"revision":7},"device":null}),
    );
    let reply = decode_reply(
        Operation::Provenance,
        &serde_json::to_vec(&expected).unwrap(),
    )
    .unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&encode_reply(&reply).unwrap()).unwrap(),
        expected
    );
}

#[test]
fn known_metadata_kinds_and_closed_envelopes_are_still_strict() {
    for model in [
        json!({"repository":true}),
        json!({"files":[]}),
        json!({"runtime":{"os":"fixture","unexpected":1}}),
    ] {
        assert!(
            decode_reply(
                Operation::Provenance,
                &serde_json::to_vec(&provenance(&json!({}), &model)).unwrap()
            )
            .is_err()
        );
    }
    let mut expected = provenance(&json!({}), &json!({}));
    expected["provenance"]["unexpected"] = json!(1);
    assert!(
        decode_reply(
            Operation::Provenance,
            &serde_json::to_vec(&expected).unwrap()
        )
        .is_err()
    );
}

#[test]
fn archival_depth_entries_and_text_have_independent_budgets() {
    let mut nested = json!(null);
    for _ in 0..33 {
        nested = json!([nested]);
    }
    for arguments in [
        json!({"nested":nested}),
        json!({"entries":vec![true;4096]}),
        json!({"text":"a".repeat(65_537)}),
    ] {
        assert!(
            decode_reply(
                Operation::Provenance,
                &serde_json::to_vec(&provenance(&arguments, &json!({}))).unwrap()
            )
            .is_err()
        );
    }
    let small = provenance(&json!({"text":"a".repeat(1024)}), &json!({}));
    assert!(decode_reply(Operation::Provenance, &serde_json::to_vec(&small).unwrap()).is_ok());
}
