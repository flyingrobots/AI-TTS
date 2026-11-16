// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: daemon provenance returns saved metadata verbatim.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::archive::{ArchiveObject, ArchiveValue};
use aitts_protocol::{decode_reply, encode_reply, operation::Operation};
use serde_json::{Value, json};
use std::collections::BTreeMap;

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
        json!({"runtime":{"os":"fixture","os_release":"1","macos":"","architecture":"fixture","python":"3.13.0","cpu_count":2,"packages":{},"unexpected":1}}),
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

#[test]
fn each_archival_budget_accepts_its_boundary_and_rejects_one_more() {
    for (count, expected) in [(65_532, true), (65_533, false)] {
        let bytes = serde_json::to_vec(&json!({"data":"a".repeat(count)})).unwrap();
        assert_eq!(
            serde_json::from_slice::<ArchiveObject>(&bytes).is_ok(),
            expected
        );
    }
    for (count, expected) in [(4094, true), (4095, false)] {
        let bytes = serde_json::to_vec(&json!({"values":vec![true;count]})).unwrap();
        assert_eq!(
            serde_json::from_slice::<ArchiveObject>(&bytes).is_ok(),
            expected
        );
    }
    for (count, expected) in [(30, true), (31, false)] {
        let mut value = Value::Null;
        for _ in 0..count {
            value = json!([value]);
        }
        let bytes = serde_json::to_vec(&json!({"value":value})).unwrap();
        assert_eq!(
            serde_json::from_slice::<ArchiveObject>(&bytes).is_ok(),
            expected
        );
    }
}

#[test]
fn historical_duplicate_keys_are_not_silently_collapsed() {
    assert!(serde_json::from_slice::<ArchiveObject>(br#"{"key":1,"key":2}"#).is_err());
    assert!(serde_json::from_slice::<ArchiveObject>(br#"{"nested":{"key":1,"key":2}}"#).is_err());
}

#[test]
fn constructed_archives_admit_utf8_bytes_before_copying_owned_values() {
    let mut entries = BTreeMap::from([("data".into(), ArchiveValue::Text("é".repeat(32_766)))]);
    let archive = ArchiveObject::try_new(&entries).unwrap();
    assert_eq!(archive.entries(), &entries);
    if let Some(ArchiveValue::Text(text)) = entries.get_mut("data") {
        text.push('é');
    }
    assert!(ArchiveObject::try_new(&entries).is_err());
    assert_ne!(archive.entries(), &entries);
}
