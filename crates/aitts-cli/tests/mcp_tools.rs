// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary directory, loopback Unix socket, one peer thread).
//! Oracle: `tests/fixtures/mcp_tool_calls.json`, the Python 3.12 `ai-tts-mcp`
//! server's `tools/call` replies and daemon requests, which
//! `tests/test_mcp_tool_parity.py` re-checks. A scripted peer gives the
//! recorded daemon replies. Every field is compared exactly, except that a
//! successful result's text content is compared as parsed JSON: it is the
//! structured result printed by Python's `json.dumps`, whose key order and
//! spacing are presentation. A call Python refuses for its arguments is
//! compared on `isError`, the text up to Pydantic's message (`Error executing
//! tool NAME:`, or the bare `Error executing tool NAME`), and no daemon request.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::{Path, PathBuf};
use std::thread::JoinHandle;

use serde_json::{Value, json};

fn cases() -> Vec<Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/mcp_tool_calls.json"
    );
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

const STOP: &[u8] = b"STOP\n";

/// Answer one connection per reply, in order, until a `STOP` line; return
/// the requests read. A connection after the replies run out gets none.
fn peer(socket: &Path, replies: Vec<Value>) -> JoinHandle<Vec<Value>> {
    let listener = UnixListener::bind(socket).unwrap();
    std::thread::spawn(move || {
        let mut seen = Vec::new();
        let mut replies = replies.into_iter();
        for stream in listener.incoming() {
            let stream = stream.unwrap();
            let mut line = Vec::new();
            BufReader::new(&stream)
                .read_until(b'\n', &mut line)
                .unwrap();
            if line == STOP {
                break;
            }
            seen.push(serde_json::from_slice(&line).unwrap());
            if let Some(reply) = replies.next() {
                let _ = (&stream).write_all(format!("{reply}\n").as_bytes());
            }
        }
        seen
    })
}

fn stop(socket: &Path, handle: JoinHandle<Vec<Value>>) -> Vec<Value> {
    std::os::unix::net::UnixStream::connect(socket)
        .unwrap()
        .write_all(STOP)
        .unwrap();
    handle.join().unwrap()
}

fn call(socket: &Path, tool: &Value, arguments: &Value) -> Value {
    let messages = [
        json!({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "parity", "version": "1"}}}),
        json!({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json!({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}),
    ];
    let mut input = messages.map(|m| m.to_string()).join("\n");
    input.push('\n');
    let mut output = Vec::new();
    aitts_cli::mcp::serve(&mut input.as_bytes(), &mut output, socket);
    let text = String::from_utf8(output).unwrap();
    serde_json::from_str(text.lines().nth(1).unwrap()).unwrap()
}

/// The reply with a successful result's text content parsed.
/// The recorded text before Pydantic's message, when Python refused the
/// arguments; `None` for every other reply.
fn refusal_prefix(reply: &Value) -> Option<String> {
    let text = reply["result"]["content"][0]["text"].as_str()?;
    if reply["result"]["isError"] != json!(true) {
        return None;
    }
    if let Some((before, _)) = text.split_once(" validation error") {
        let (head, _) = before.rsplit_once(':')?;
        return Some(format!("{head}:"));
    }
    (text.starts_with("Error executing tool ") && !text.contains(':')).then(|| text.to_owned())
}

fn comparable(mut reply: Value) -> Value {
    if let Some(prefix) = refusal_prefix(&reply) {
        let text = reply["result"]["content"][0]["text"]
            .as_str()
            .unwrap_or_default();
        let kept = if text.starts_with(&prefix) {
            prefix
        } else {
            text.to_owned()
        };
        reply["result"]["content"][0]["text"] = json!(kept);
        return reply;
    }
    let result = &mut reply["result"];
    if result["isError"] == json!(false) {
        let text = result["content"][0]["text"].as_str().unwrap().to_owned();
        result["content"][0]["text"] = serde_json::from_str(&text).unwrap();
    }
    reply
}

#[test]
fn each_tool_call_gets_the_python_servers_reply_and_sends_its_requests() {
    let mut failures = Vec::new();
    for case in cases() {
        let dir = tempfile::tempdir().unwrap();
        let replies = case["daemon_replies"].as_array().unwrap().clone();
        let socket: PathBuf = if case["socket"] == json!("peer") {
            dir.path().join("peer.sock")
        } else {
            PathBuf::from("/nonexistent/ai-tts.sock")
        };
        let handle = (!replies.is_empty()).then(|| peer(&socket, replies));
        let reply = call(&socket, &case["tool"], &case["arguments"]);
        let sent = handle.map_or_else(Vec::new, |handle| stop(&socket, handle));
        if sent != *case["daemon_requests"].as_array().unwrap() {
            failures.push(format!("{}: sent {sent:?}", case["tool"]));
        }
        let expected = case["reply"].clone();
        let actual = match refusal_prefix(&expected) {
            // Keep only Python's prefix of the Rust text, so the rest may differ.
            Some(prefix) => {
                let mut actual = reply.clone();
                let text = actual["result"]["content"][0]["text"]
                    .as_str()
                    .unwrap_or_default();
                let kept = if text.starts_with(&prefix) {
                    prefix.clone()
                } else {
                    text.to_owned()
                };
                actual["result"]["content"][0]["text"] = json!(kept);
                actual
            }
            None => comparable(reply.clone()),
        };
        if actual != comparable(expected) {
            failures.push(format!("{}: replied {reply}", case["tool"]));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Regression for #211. Oracle: the protocol's `Requeued` reply
/// (`aitts-protocol` `control_reply.rs`), which always carries `composite`
/// and `segment_count`; the tool result must succeed and carry them.
#[test]
fn requeue_speech_returns_the_daemons_requeued_reply() {
    let dir = tempfile::tempdir().unwrap();
    let socket = dir.path().join("peer.sock");
    let id = format!("utt_{}2", "0".repeat(31));
    let reply = json!({"ok": true, "id": id, "state": "Ready", "priority": "urgent",
        "composite": true, "segment_count": 3});
    let handle = peer(&socket, vec![reply]);
    let answer = call(
        &socket,
        &json!("requeue_speech"),
        &json!({"utterance_id": id, "priority": "urgent"}),
    );
    stop(&socket, handle);
    assert_eq!(
        answer["result"]["structuredContent"],
        json!({"id": id, "state": "Ready", "priority": "urgent",
            "composite": true, "segment_count": 3}),
        "requeue_speech result: {answer}"
    );
}

fn json_value() -> impl proptest::strategy::Strategy<Value = Value> {
    use proptest::prelude::*;
    let leaf = prop_oneof![
        Just(Value::Null),
        any::<bool>().prop_map(Value::Bool),
        any::<i64>().prop_map(|n| json!(n)),
        (-1.0e6..1.0e6f64).prop_map(|n| json!(n)),
        "[a-z_]{0,8}".prop_map(Value::String),
        Just(json!("utt_0123456789abcdef0123456789abcdef")),
    ];
    leaf.prop_recursive(3, 16, 4, |inner| {
        prop_oneof![
            proptest::collection::vec(inner.clone(), 0..4).prop_map(Value::Array),
            proptest::collection::btree_map("[a-z_]{1,8}", inner, 0..4)
                .prop_map(|map| Value::Object(map.into_iter().collect())),
        ]
    })
}

proptest::proptest! {
    #![proptest_config(proptest::prelude::ProptestConfig::with_cases(256))]
    /// Oracle: the MCP tool result shape. Any daemon reply, recorded or with one
    /// field replaced by random JSON, gives a result that is either an error or
    /// a structured result whose text is the same JSON; never a panic.
    #[test]
    fn any_daemon_reply_gives_a_well_formed_tool_result(
        index in 0usize..1000,
        pick in proptest::prelude::any::<usize>(),
        replacement in json_value(),
        replace in proptest::prelude::any::<bool>(),
    ) {
        let cases: Vec<Value> = cases()
            .into_iter()
            .filter(|case| case["socket"] == json!("peer"))
            .collect();
        let case = &cases[index % cases.len()];
        let mut reply = case["daemon_replies"][0].clone();
        if replace {
            let keys: Vec<String> = reply.as_object().unwrap().keys().cloned().collect();
            let key = keys[pick % keys.len()].clone();
            reply[key] = replacement;
        }
        let dir = tempfile::tempdir().unwrap();
        let socket = dir.path().join("peer.sock");
        let handle = peer(&socket, vec![reply]);
        let result = call(&socket, &case["tool"], &case["arguments"])["result"].clone();
        stop(&socket, handle);
        let is_error = result["isError"].as_bool();
        proptest::prop_assert!(is_error.is_some(), "{result}");
        let text = result["content"][0]["text"].as_str().unwrap_or_default().to_owned();
        if is_error == Some(false) {
            let printed: Value = serde_json::from_str(&text).unwrap();
            proptest::prop_assert_eq!(printed, result["structuredContent"].clone());
        } else {
            proptest::prop_assert!(text.starts_with("Error executing tool "), "{text}");
        }
    }
}

const ARGUMENT_TOOLS: [&str; 6] = [
    "enqueue_speech",
    "requeue_speech",
    "list_speech_history",
    "set_captions_enabled",
    "assign_speech_voice",
    "cancel_queued_speech",
];

/// Random arguments: each tool's own keys and a stray key, with values that
/// are often right, often near misses, and sometimes arbitrary JSON.
fn arguments(tool: &str) -> impl proptest::strategy::Strategy<Value = Value> {
    use proptest::prelude::*;
    let own: Vec<&'static str> = match tool {
        "enqueue_speech" => vec![
            "text",
            "content_format",
            "voice",
            "speed",
            "sensitivity",
            "priority",
            "preempt",
            "source",
        ],
        "requeue_speech" => vec!["utterance_id", "priority"],
        "list_speech_history" => vec!["limit", "before"],
        "set_captions_enabled" => vec!["enabled"],
        "assign_speech_voice" => vec!["source", "voice"],
        _ => vec!["utterance_id"],
    };
    let any_key = proptest::sample::select(vec![
        "text",
        "content_format",
        "voice",
        "speed",
        "sensitivity",
        "priority",
        "preempt",
        "source",
        "utterance_id",
        "limit",
        "before",
        "enabled",
        "stray",
    ]);
    let key = prop_oneof![3 => proptest::sample::select(own), 1 => any_key];
    let near = proptest::sample::select(vec![
        json!("Hello."),
        json!(""),
        json!("  "),
        json!("markdown"),
        json!("urgent"),
        json!("public"),
        json!("af_bella"),
        json!("utt_0123456789abcdef0123456789abcdef"),
        json!("utt_bad"),
        json!(1.5),
        json!(3),
        json!(0),
        json!(-1),
        json!(2.5),
        json!("1.25"),
        json!("yes"),
        json!(1.0e9),
        json!("1e400"),
        json!(-0.0),
        json!("maybe"),
        json!(true),
        json!(false),
        json!(1),
        json!(null),
    ]);
    let extreme = any::<f64>()
        .prop_filter("finite", |n| n.is_finite())
        .prop_map(|n| json!(n));
    let item = prop_oneof![4 => near, 1 => extreme, 1 => json_value()];
    proptest::collection::btree_map(key, item, 0..3)
        .prop_map(|map| Value::Object(map.into_iter().map(|(k, v)| (k.to_owned(), v)).collect()))
}

fn valid(tool: &str) -> Value {
    let id = "utt_0123456789abcdef0123456789abcdef";
    match tool {
        "enqueue_speech" => json!({"text": "Hello."}),
        "requeue_speech" | "cancel_queued_speech" => json!({"utterance_id": id}),
        "set_captions_enabled" => json!({"enabled": true}),
        "assign_speech_voice" => json!({"source": "agent", "voice": "af_bella"}),
        _ => json!({}),
    }
}

/// Oracle: the tool-call contract. Random arguments never panic, always give
/// a well-formed result, and a call refused for its arguments sends no daemon
/// request. The corpus is seeded (`AITTS_FUZZ_SEED`, printed) and classified,
/// and each class must be reached so the property is not vacuous.
#[test]
fn random_arguments_are_refused_before_any_daemon_request() {
    use proptest::strategy::{Strategy, ValueTree};
    use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};
    let seed: u64 = std::env::var("AITTS_FUZZ_SEED")
        .ok()
        .and_then(|seed| seed.parse().ok())
        .unwrap_or(139);
    eprintln!("AITTS_FUZZ_SEED={seed}");
    let mut bytes = [0u8; 32];
    bytes[..8].copy_from_slice(&seed.to_le_bytes());
    let mut runner = TestRunner::new_with_rng(
        Config::default(),
        TestRng::from_seed(RngAlgorithm::ChaCha, &bytes),
    );
    let submit = cases()
        .into_iter()
        .find(|case| case["tool"] == json!("enqueue_speech") && case["socket"] == json!("peer"))
        .map(|case| case["daemon_replies"][0].clone())
        .unwrap();
    let (mut accepted, mut refused, mut failed) = (0, 0, 0);
    for round in 0..1200 {
        let tool = ARGUMENT_TOOLS[round % ARGUMENT_TOOLS.len()];
        // A valid call for the tool, with up to two keys changed or added.
        let mut args = valid(tool);
        let changes = arguments(tool).new_tree(&mut runner).unwrap().current();
        for (key, value) in changes.as_object().unwrap() {
            args[key.as_str()] = value.clone();
        }
        let dir = tempfile::tempdir().unwrap();
        let socket = dir.path().join("peer.sock");
        let handle = peer(&socket, vec![submit.clone()]);
        let result = call(&socket, &json!(tool), &args)["result"].clone();
        let sent = stop(&socket, handle);
        let text = result["content"][0]["text"].as_str().unwrap_or_default();
        let context = format!("seed {seed}, round {round}: {tool} {args} -> {result}");
        match result["isError"].as_bool() {
            Some(false) => {
                accepted += 1;
                let printed: Value = serde_json::from_str(text).unwrap();
                assert_eq!(printed, result["structuredContent"], "{context}");
                assert_eq!(sent.len(), 1, "{context}");
            }
            Some(true) if sent.is_empty() => {
                refused += 1;
                assert!(
                    text.starts_with(&format!("Error executing tool {tool}")),
                    "{context}"
                );
            }
            Some(true) => {
                failed += 1;
                assert_eq!(sent.len(), 1, "{context}");
                assert!(
                    text.starts_with(&format!("Error executing tool {tool}: ")),
                    "{context}"
                );
            }
            None => panic!("no isError: {context}"),
        }
    }
    eprintln!("corpus: {accepted} accepted, {refused} refused, {failed} daemon or schema failures");
    assert!(
        accepted > 0 && refused > 0 && failed > 0,
        "a class was never reached"
    );
}
