// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: closed records are JSON objects and vocabularies are JSON strings.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{
    decode_event, decode_reply, decode_request,
    operation::Operation,
    status::{Accepting, InputIdle, ListenerSpeaking},
    vocabulary::{ModelState, Queue, State},
};
use serde_json::{Value, json};

fn line(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).unwrap()
}

#[test]
fn closed_records_refuse_the_array_form_at_top_level_and_nested() {
    let object = json!({"ok":true,"engines":[{"name":"x","is_local":true,"voices":[],"state":"ready","selected":true}],"models":[]});
    assert!(decode_reply(Operation::Engines, &line(&object)).is_ok());
    let nested = json!({"ok":true,"engines":[["x",true,[],"ready",true]],"models":[]});
    assert!(decode_reply(Operation::Engines, &line(&nested)).is_err());
    let top = json!([true, [], []]);
    assert!(decode_reply(Operation::Engines, &line(&top)).is_err());
    let nested_in_status = json!({"ok":true,"accepting_speech":true,"counts":{},"current":null,
        "engine":"fake","input_active":false,"playback_held":false,"playback_state":"idle",
        "state":"accepting","submission_disposition":"queued_for_playback",
        "submission_guidance":"g","version":"0","voice":"v",
        "engine_preparing":["synthetic/model", 1]});
    assert!(decode_reply(Operation::Status, &line(&nested_in_status)).is_err());
    for request in [json!(["status"]), json!(["list", "input"])] {
        assert!(decode_request(&line(&request)).is_err(), "{request}");
    }
    let settings = json!({"op":"settings","set":[true]});
    assert!(decode_request(&line(&settings)).is_err());
    let event = json!(["state_changed", "utt_1", null, "Queued", 1]);
    assert!(decode_event(&line(&event)).is_err());
}

#[test]
fn string_vocabularies_refuse_the_single_entry_map_form() {
    assert!(decode_request(&line(&json!({"op":"list","queue":"input"}))).is_ok());
    for request in [
        json!({"op":"list","queue":{"input":null}}),
        json!({"op":"submit","text":"t","priority":{"urgent":null}}),
        json!({"op":"clear","queue":{"history":null}}),
    ] {
        assert!(decode_request(&line(&request)).is_err(), "{request}");
    }
    let engines = json!({"ok":true,"engines":[{"name":"x","is_local":true,"voices":[],"state":{"ready":null},"selected":true}],"models":[]});
    assert!(decode_reply(Operation::Engines, &line(&engines)).is_err());
    let event =
        json!({"event":"state_changed","id":"utt_1","from":null,"to":{"Queued":null},"at":1});
    assert!(decode_event(&line(&event)).is_err());
    assert!(serde_json::from_value::<Operation>(json!({"status":null})).is_err());
    assert!(serde_json::from_value::<Queue>(json!({"input":null})).is_err());
    assert!(serde_json::from_value::<State>(json!({"Queued":null})).is_err());
    assert!(serde_json::from_value::<ModelState>(json!({"ready":null})).is_err());
    assert!(serde_json::from_value::<Accepting>(json!({"accepting":null})).is_err());
    assert!(serde_json::from_value::<ListenerSpeaking>(json!({"listener_speaking":null})).is_err());
    assert!(serde_json::from_value::<InputIdle>(json!({"input_idle":null})).is_err());
    assert_eq!(
        serde_json::from_value::<Accepting>(json!("accepting")).unwrap(),
        Accepting::Value
    );
}
