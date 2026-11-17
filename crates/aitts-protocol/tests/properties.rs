// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: JSON equality on generated values in source-derived wire shapes.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_protocol::{
    decode_event, decode_reply, decode_request, encode_event, encode_reply, encode_request,
    operation::Operation,
};
use proptest::prelude::*;
use serde_json::{Number, Value, json};

fn vocabulary(key: &str, value: &str) -> &'static [&'static str] {
    const STATES: &[&str] = &[
        "Submitted",
        "Queued",
        "Synthesizing",
        "Ready",
        "Playing",
        "Paused",
        "Played",
        "Skipped",
        "Cancelled",
        "Failed",
    ];
    const MODELS: &[&str] = &[
        "cold",
        "loading",
        "ready",
        "reloading",
        "failed",
        "server managed",
        "not installed",
        "installing",
        "cancelled",
    ];
    match key {
        "state" | "from" | "to" | "final_state" if STATES.contains(&value) => STATES,
        "state" | "model_state" if MODELS.contains(&value) => MODELS,
        "sensitivity" => &["public", "internal", "confidential"],
        "priority" => &["normal", "urgent", "preempt"],
        "content_format" => &["plain_text", "markdown"],
        "input_interrupt_resume" => &["manual", "when_idle"],
        "playback_state" => &["idle", "synthesizing", "playing", "paused"],
        "submission_disposition" => &[
            "queued_for_playback",
            "spooled_until_resume",
            "synthesis_only",
        ],
        _ => &[],
    }
}

fn vary(value: &mut Value, key: &str, text: &str, integer: u16, flag: bool) {
    match value {
        Value::Object(fields) => {
            for (key, child) in fields {
                vary(child, key, text, integer, flag);
            }
        }
        Value::Array(values) => {
            for child in values {
                vary(child, key, text, integer, flag);
            }
        }
        Value::String(value) if !vocabulary(key, value).is_empty() => {
            let choices = vocabulary(key, value);
            choices
                .get(usize::from(integer) % choices.len())
                .copied()
                .unwrap()
                .clone_into(value);
        }
        Value::String(value)
            if matches!(
                key,
                "text"
                    | "source"
                    | "voice"
                    | "message"
                    | "origin"
                    | "submission_guidance"
                    | "title"
                    | "description"
                    | "preview"
                    | "id"
                    | "artifact_id"
                    | "utterance_id"
                    | "replay_of"
                    | "current"
                    | "replay_id"
            ) =>
        {
            text.clone_into(value);
        }
        Value::Number(value) => {
            *value = if value.is_f64() {
                Number::from_f64(f64::from(integer) + 0.25).unwrap()
            } else {
                u64::from(integer).into()
            };
        }
        Value::Bool(value)
            if !matches!(key, "ok" | "accepted" | "accepting_speech" | "subscribed") =>
        {
            *value = flag;
        }
        _ => {}
    }
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(64))]

    #[test]
    fn generated_values_round_trip_every_request_reply_and_event_shape(
        text in ".{0,40}", integer in 1u16..65_535, flag in any::<bool>(),
    ) {
        let requests: Vec<Value> = serde_json::from_str(include_str!("fixtures/requests.json")).unwrap();
        for mut expected in requests {
            vary(&mut expected, "", &text, integer, flag);
            let request = decode_request(&serde_json::to_vec(&expected).unwrap()).unwrap();
            prop_assert_eq!(serde_json::from_slice::<Value>(&encode_request(&request).unwrap()).unwrap(), expected);
        }
        let replies: Vec<Value> = serde_json::from_str(include_str!("fixtures/replies.json")).unwrap();
        for record in replies {
            let op: Operation = serde_json::from_value(record.get("op").unwrap().clone()).unwrap();
            let mut expected = record.get("reply").unwrap().clone();
            vary(&mut expected, "", &text, integer, flag);
            let reply = decode_reply(op, &serde_json::to_vec(&expected).unwrap()).unwrap();
            prop_assert_eq!(serde_json::from_slice::<Value>(&encode_reply(&reply).unwrap()).unwrap(), expected);
        }
        let events: Vec<Value> = serde_json::from_str(include_str!("fixtures/events.json")).unwrap();
        for mut expected in events {
            vary(&mut expected, "", &text, integer, flag);
            let event = decode_event(&serde_json::to_vec(&expected).unwrap()).unwrap();
            prop_assert_eq!(serde_json::from_slice::<Value>(&encode_event(&event).unwrap()).unwrap(), expected);
        }
    }

    #[test]
    fn generated_optional_fields_preserve_absence_null_and_supplied_text(
        source in ".{0,40}", choice in 0u8..3, playback in any::<bool>(),
    ) {
        let mut expected = json!({"op":"submit","text":"Generated case.","playback":playback});
        match choice {
            0 => {},
            1 => { expected.as_object_mut().unwrap().insert("source".into(), Value::Null); },
            _ => { expected.as_object_mut().unwrap().insert("source".into(), source.into()); },
        }
        let request = decode_request(&serde_json::to_vec(&expected).unwrap()).unwrap();
        prop_assert_eq!(serde_json::from_slice::<Value>(&encode_request(&request).unwrap()).unwrap(), expected);
    }
}
