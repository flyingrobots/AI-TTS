// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module runs `tools/call` as the Python server's
//! `UnixSocketSpeechAdapter` does: one daemon request per tool, the reply
//! without `ok` checked against the tool's recorded output schema, and a
//! failure reported as `isError` text `Error executing tool NAME: CODE: MESSAGE`.

use crate::mcp_schema::conform;
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

/// As the Python client: each socket read and write waits at most 10 seconds.
const LIMIT: Duration = Duration::from_secs(10);

/// A failure with the Python `SpeechServiceError` code and message.
struct Failure(String, String);

/// `[Errno 2] No such file or directory`, as Python prints an `OSError`.
fn python_os_error(error: &std::io::Error) -> String {
    let text = error.to_string();
    match error.raw_os_error() {
        Some(code) => {
            let reason = text.split(" (os error").next().unwrap_or(&text);
            format!("[Errno {code}] {reason}")
        }
        None => text,
    }
}

fn unreachable(message: String) -> Failure {
    Failure("unreachable".into(), message)
}

/// One request and its parsed reply, with the Python client's failures.
fn request(socket: &Path, payload: &Value) -> Result<Value, Failure> {
    let stream = UnixStream::connect(socket).map_err(|error| {
        unreachable(format!(
            "cannot reach the daemon at {}: {}",
            socket.display(),
            python_os_error(&error)
        ))
    })?;
    let timed_out = || unreachable("timed out waiting for the daemon's response".into());
    let io = |error: std::io::Error| match error.kind() {
        ErrorKind::WouldBlock | ErrorKind::TimedOut => timed_out(),
        _ => unreachable(python_os_error(&error)),
    };
    stream.set_read_timeout(Some(LIMIT)).map_err(io)?;
    stream.set_write_timeout(Some(LIMIT)).map_err(io)?;
    (&stream)
        .write_all(format!("{payload}\n").as_bytes())
        .map_err(io)?;
    let mut line = Vec::new();
    BufReader::new(&stream)
        .read_until(b'\n', &mut line)
        .map_err(io)?;
    if !line.ends_with(b"\n") {
        return Err(unreachable(
            "the daemon closed the connection without answering".into(),
        ));
    }
    let reply: Value = serde_json::from_slice(&line)
        .ok()
        .filter(Value::is_object)
        .ok_or_else(|| unreachable("daemon returned invalid JSONL".into()))?;
    if reply.get("ok") == Some(&json!(true)) {
        return Ok(reply);
    }
    let error = reply.get("error").cloned().unwrap_or_else(|| json!({}));
    let text = |key: &str, fallback: &str| {
        error
            .get(key)
            .and_then(Value::as_str)
            .unwrap_or(fallback)
            .to_owned()
    };
    Err(Failure(text("type", "internal"), text("message", "")))
}

fn field(reply: Value, name: &str) -> Value {
    match reply {
        Value::Object(mut map) => map.remove(name).unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

fn captions(reply: Value) -> Value {
    json!({"enabled": field(field(reply, "settings"), "captions_enabled")})
}

/// Turns a daemon reply into the public result before the schema check.
type Public = fn(Value) -> Value;

/// The daemon request for a tool without arguments, and its [`Public`] step.
fn plan(tool: &str) -> Option<(Value, Public)> {
    fn without_ok(mut reply: Value) -> Value {
        if let Value::Object(map) = &mut reply {
            map.remove("ok");
        }
        reply
    }
    fn plan_items(reply: Value) -> Value {
        json!({"items": field(reply, "plan")})
    }
    let op = |op: &str| json!({"op": op});
    Some(match tool {
        "speech_status" => (op("status"), without_ok),
        "list_speech_queue" => (json!({"op": "snapshot", "limit": 1}), plan_items),
        "speech_metrics" => (op("metrics"), without_ok),
        "list_speech_voices" => (op("voices"), without_ok),
        "get_caption_settings" => (op("settings"), captions),
        "pause_speech_playback" => (op("pause"), without_ok),
        "resume_speech_playback" => (op("resume"), without_ok),
        "skip_current_speech" => (op("skip"), without_ok),
        "restart_current_speech" => (op("rewind"), without_ok),
        "next_speech_chunk" => (op("next_segment"), without_ok),
        "previous_speech_chunk" => (op("previous_segment"), without_ok),
        "resume_speech_when_input_idle" => (op("resume_when_input_idle"), without_ok),
        "list_speech_voice_assignments" => (op("voice_assignments"), without_ok),
        "clear_speech_queue" => (json!({"op": "clear", "queue": "queue"}), without_ok),
        "purge_cached_audio" => (op("purge_cache"), without_ok),
        _ => return None,
    })
}

/// String arguments that Pydantic strips before it checks them (`NonEmptyText`).
fn stripped(tool: &str, field: &str) -> bool {
    matches!(
        (tool, field),
        ("enqueue_speech", "text" | "voice" | "source")
            | ("assign_speech_voice", "source" | "voice")
    )
}

/// A call refused before any daemon request. `bare` is the Python text for a
/// failure in the second model (`EnqueueSpeech`), which has no message.
struct Refused {
    bare: bool,
}

/// The daemon request for a tool with arguments, from its checked arguments.
fn argument_request(tool: &str, args: &Value) -> Option<Result<(Value, Public), Refused>> {
    fn items(reply: Value) -> Value {
        match reply {
            Value::Object(mut map) => json!({"items": map.remove("items").unwrap_or(Value::Null)}),
            _ => json!({"items": null}),
        }
    }
    let get = |key: &str| args.get(key).filter(|value| !value.is_null()).cloned();
    let without_ok: Public = |mut reply| {
        if let Value::Object(map) = &mut reply {
            map.remove("ok");
        }
        reply
    };
    Some(Ok(match tool {
        "enqueue_speech" => {
            // EnqueueSpeech requires these, when present, to be non-empty after stripping.
            if ["voice", "source"]
                .iter()
                .any(|key| get(key).is_some_and(|value| value == json!("")))
            {
                return Some(Err(Refused { bare: true }));
            }
            let mut payload = json!({"op": "submit", "origin": "MCP"});
            for key in [
                "text",
                "content_format",
                "voice",
                "speed",
                "sensitivity",
                "priority",
                "preempt",
                "source",
            ] {
                if let (Some(value), Value::Object(map)) = (get(key), &mut payload) {
                    map.insert(key.to_owned(), value);
                }
            }
            (payload, without_ok)
        }
        "requeue_speech" => (
            json!({"op": "requeue", "id": get("utterance_id"), "priority": get("priority")}),
            without_ok,
        ),
        "list_speech_history" => {
            let mut payload = json!({"op": "history", "limit": get("limit")});
            if let (Some(before), Value::Object(map)) = (get("before"), &mut payload) {
                map.insert("before".into(), before);
            }
            (payload, items)
        }
        "set_captions_enabled" => (
            json!({"op": "settings", "set": {"captions_enabled": get("enabled")}}),
            captions,
        ),
        "assign_speech_voice" => {
            let payload = match get("voice") {
                Some(voice) => {
                    json!({"op": "assign_voice", "source": get("source"), "voice": voice})
                }
                None => json!({"op": "assign_voice", "source": get("source"), "release": true}),
            };
            (payload, without_ok)
        }
        "cancel_queued_speech" => (
            json!({"op": "cancel", "id": get("utterance_id")}),
            without_ok,
        ),
        _ => return None,
    }))
}

/// The checked arguments, with `NonEmptyText` fields stripped first.
fn checked_arguments(
    tool: &str,
    arguments: Option<&Value>,
    schema: &Value,
) -> Result<Value, Refused> {
    let mut args = match arguments {
        None | Some(Value::Null) => json!({}),
        Some(Value::Object(map)) => Value::Object(map.clone()),
        Some(_) => return Err(Refused { bare: false }),
    };
    if let Value::Object(map) = &mut args {
        for (key, value) in map.iter_mut() {
            if let (true, Some(text)) = (stripped(tool, key), value.as_str()) {
                *value = json!(text.trim());
            }
        }
    }
    let defs = schema.get("$defs").unwrap_or(&Value::Null);
    conform(&args, schema, defs).map_err(|_| Refused { bare: false })
}

fn text_result(text: &str, is_error: bool) -> Value {
    json!({"content": [{"type": "text", "text": text}], "isError": is_error})
}

/// The `tools/call` result for `tool`, given the recorded tool catalog.
pub(crate) fn call(
    tool: &str,
    arguments: Option<&Value>,
    catalog: &[Value],
    socket: &Path,
) -> Value {
    let Some(described) = catalog.iter().find(|entry| entry["name"] == json!(tool)) else {
        return text_result(&format!("Unknown tool: {tool}"), true);
    };
    let planned = match plan(tool) {
        Some(planned) => Ok(planned),
        None => match checked_arguments(tool, arguments, &described["inputSchema"])
            .map(|args| argument_request(tool, &args))
        {
            Ok(Some(planned)) => planned,
            Ok(None) => return text_result(&format!("Unknown tool: {tool}"), true),
            Err(refused) => Err(refused),
        },
    };
    let (payload, public) = match planned {
        Ok(planned) => planned,
        Err(Refused { bare: true }) => {
            return text_result(&format!("Error executing tool {tool}"), true);
        }
        Err(Refused { bare: false }) => {
            return text_result(
                &format!("Error executing tool {tool}: invalid arguments for {tool}"),
                true,
            );
        }
    };
    let schema = &described["outputSchema"];
    let defs = schema.get("$defs").unwrap_or(&Value::Null);
    let outcome = request(socket, &payload).and_then(|reply| {
        conform(&public(reply), schema, defs).map_err(|_| {
            let title = schema["title"].as_str().unwrap_or("result");
            Failure(
                "invalid_response".into(),
                format!("daemon returned a response outside the public {title} schema"),
            )
        })
    });
    match outcome {
        Ok(result) => {
            let text = serde_json::to_string_pretty(&result).unwrap_or_default();
            json!({
                "content": [{"type": "text", "text": text}],
                "isError": false,
                "structuredContent": result,
            })
        }
        Err(Failure(code, message)) => text_result(
            &format!("Error executing tool {tool}: {code}: {message}"),
            true,
        ),
    }
}
