// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module turns parsed arguments into the request object that
//! `aitts.cli._payload_for` builds, before the typed wire check.

use clap::ArgMatches;
use serde_json::{Map, Value, json};

/// A command line that parses but cannot form a request (Python `SystemExit(msg)`).
#[derive(Debug)]
pub(crate) struct Refused(pub(crate) String);

fn text(matches: &ArgMatches, name: &str) -> Option<Value> {
    matches.get_one::<String>(name).map(|value| json!(value))
}

fn finite(value: f64) -> Result<Value, Refused> {
    serde_json::Number::from_f64(value)
        .map(Value::Number)
        .ok_or_else(|| Refused(format!("{value} is not a finite number")))
}

fn say(matches: &ArgMatches) -> Result<Value, Refused> {
    let mut payload = Map::new();
    payload.insert("op".into(), json!("submit"));
    payload.insert("origin".into(), json!("CLI"));
    for (key, arg) in [("text", "text"), ("content_format", "format")] {
        payload.insert(key.into(), text(matches, arg).unwrap_or(Value::Null));
    }
    if matches.get_flag("preempt") {
        payload.insert("preempt".into(), json!(true));
    }
    for key in ["voice", "engine", "sensitivity", "priority", "source"] {
        if let Some(value) = text(matches, key) {
            payload.insert(key.into(), value);
        }
    }
    if let Some(speed) = matches.get_one::<f64>("speed") {
        payload.insert("speed".into(), finite(*speed)?);
    }
    Ok(Value::Object(payload))
}

fn assign_voice(matches: &ArgMatches) -> Result<Value, Refused> {
    let source = text(matches, "source");
    match (matches.get_flag("release"), text(matches, "voice")) {
        (true, None) => Ok(json!({"op": "assign_voice", "source": source, "release": true})),
        (true, Some(_)) => Err(Refused("--release does not take a voice".into())),
        (false, Some(voice)) => Ok(json!({"op": "assign_voice", "source": source, "voice": voice})),
        (false, None) => Err(Refused(
            "assign-voice needs a voice, or --release to forget the assignment".into(),
        )),
    }
}

fn setting(key: &str, value: &str) -> Result<(String, Value), Refused> {
    let key = match key {
        "earcon" => "earcon_enabled",
        "ducking" => "ducking_enabled",
        other => other,
    };
    let value = match (key, value) {
        ("earcon_enabled" | "ducking_enabled", "on") => "true",
        ("earcon_enabled" | "ducking_enabled", "off") => "false",
        _ => value,
    };
    let converted = match key {
        "speed" | "playback_rate" => {
            let number = value
                .trim()
                .parse::<f64>()
                .map_err(|_| Refused(format!("{key} must be a number")))?;
            finite(number)?
        }
        "captions_enabled" | "input_interrupt_enabled" | "earcon_enabled" | "ducking_enabled" => {
            match value {
                "true" => json!(true),
                "false" => json!(false),
                _ => return Err(Refused(format!("{key} must be true or false"))),
            }
        }
        "voice_languages" => json!(value.split(',').collect::<Vec<_>>()),
        _ => json!(value),
    };
    Ok((key.to_owned(), converted))
}

fn settings(matches: &ArgMatches) -> Result<Value, Refused> {
    let mut pairs: Vec<String> = matches
        .get_many::<String>("set")
        .map_or_else(Vec::new, |values| values.cloned().collect());
    if matches.get_one::<String>("action").is_some() {
        match (
            matches.get_one::<String>("key"),
            matches.get_one::<String>("value"),
        ) {
            (Some(key), Some(value)) => pairs.push(format!("{key}={value}")),
            _ => return Err(Refused("settings set requires KEY VALUE".into())),
        }
    }
    for key in ["engine", "earcon", "ducking"] {
        if let Some(value) = matches.get_one::<String>(key) {
            pairs.push(format!("{key}={value}"));
        }
    }
    let mut updates = Map::new();
    for pair in &pairs {
        let Some((key, value)) = pair.split_once('=') else {
            return Err(Refused(format!("--set expects KEY=VALUE, got {pair:?}")));
        };
        let (key, value) = setting(key, value)?;
        updates.insert(key, value);
    }
    Ok(if updates.is_empty() {
        json!({"op": "settings"})
    } else {
        json!({"op": "settings", "set": updates})
    })
}

/// The request object for subcommand `name`, as the Python CLI builds it.
pub(crate) fn payload(name: &str, matches: &ArgMatches) -> Result<Value, Refused> {
    let field = |key: &str| text(matches, key);
    Ok(match name {
        "say" => return say(matches),
        "assign-voice" => return assign_voice(matches),
        "settings" => return settings(matches),
        "model-setup" => json!({"op": "model_setup", "name": field("name")}),
        "get" | "cancel" => json!({"op": name, "id": field("id")}),
        "list" | "clear" => json!({"op": name, "queue": field("queue")}),
        "history" => {
            let mut payload = json!({"op": "history", "limit": matches.get_one::<i64>("limit")});
            if let (Some(before), Value::Object(map)) = (field("before"), &mut payload)
                && before != json!("")
            {
                map.insert("before".into(), before);
            }
            payload
        }
        "rewind" => match field("to") {
            Some(to) if to != json!("") => json!({"op": "rewind", "to": to}),
            _ => json!({"op": "rewind"}),
        },
        "next-chunk" => json!({"op": "next_segment"}),
        "prev-chunk" => json!({"op": "previous_segment"}),
        "resume-when-idle" => json!({"op": "resume_when_input_idle"}),
        "voice-map" => json!({"op": "voice_assignments"}),
        other => json!({"op": other.replace('-', "_")}),
    })
}
