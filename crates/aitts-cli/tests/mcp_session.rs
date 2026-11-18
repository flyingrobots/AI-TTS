// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; no socket is opened by these methods).
//! Oracle: `tests/fixtures/mcp_session.json`, the replies of the Python
//! `ai-tts-mcp` server, which `tests/test_mcp_parity_table.py` re-checks.
//! `null` marks a message that server does not answer.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use proptest::prelude::*;
use serde_json::{Value, json};
use std::path::Path;

fn sessions() -> Vec<Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/mcp_session.json"
    );
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

/// Serve `lines` in process; return every stdout line, parsed.
fn serve(lines: &[String]) -> Vec<Value> {
    let mut input = lines.join("\n");
    input.push('\n');
    let mut output = Vec::new();
    aitts_cli::mcp::serve(
        &mut input.as_bytes(),
        &mut output,
        Path::new("/nonexistent/ai-tts.sock"),
    );
    let text = String::from_utf8(output).unwrap();
    text.lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn line(message: &Value) -> String {
    message
        .as_str()
        .map_or_else(|| message.to_string(), str::to_owned)
}

#[test]
fn each_session_gets_the_python_servers_replies() {
    let mut failures = Vec::new();
    for (index, session) in sessions().iter().enumerate() {
        let lines: Vec<String> = session["messages"]
            .as_array()
            .unwrap()
            .iter()
            .map(line)
            .collect();
        let expected: Vec<Value> = session["replies"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|reply| !reply.is_null())
            .cloned()
            .collect();
        let actual = serve(&lines);
        if actual != expected {
            failures.push(format!("session {index}: {lines:?}\n  got {actual:?}"));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

const METHODS: &[&str] = &[
    "initialize",
    "ping",
    "tools/list",
    "prompts/list",
    "resources/list",
    "tools/call",
    "notifications/initialized",
    "bogus",
];

fn message() -> impl Strategy<Value = String> {
    let id = prop_oneof![
        Just(json!(1)),
        Just(json!("a")),
        Just(Value::Null),
        any::<i64>().prop_map(|n| json!(n))
    ];
    let params = prop_oneof![
        Just(Value::Null),
        Just(json!({})),
        Just(
            json!({"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "f", "version": "1"}})
        ),
        Just(json!({"name": "speech_status", "arguments": {}})),
        any::<String>().prop_map(|text| json!({"protocolVersion": text})),
    ];
    prop_oneof![
        4 => (proptest::sample::select(METHODS), id, params, any::<bool>()).prop_map(
            |(method, id, params, with_id)| {
                let mut message = json!({"jsonrpc": "2.0", "method": method});
                if with_id { message["id"] = id; }
                if !params.is_null() { message["params"] = params; }
                message.to_string()
            }
        ),
        1 => "[^\n]*",
    ]
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(512))]
    /// Oracle: MCP stdio; stdout carries only JSON-RPC messages, each answering a request.
    #[test]
    fn random_messages_get_only_json_rpc_replies(lines in proptest::collection::vec(message(), 0..8)) {
        for reply in serve(&lines) {
            prop_assert_eq!(&reply["jsonrpc"], &json!("2.0"));
            prop_assert!(reply.get("result").is_some() != reply.get("error").is_some(), "{reply}");
        }
    }
}
