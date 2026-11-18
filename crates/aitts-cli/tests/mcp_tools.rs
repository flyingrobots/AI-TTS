// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary directory, loopback Unix socket, one peer thread).
//! Oracle: `tests/fixtures/mcp_tool_calls.json`, the Python 3.12 `ai-tts-mcp`
//! server's `tools/call` replies and daemon requests, which
//! `tests/test_mcp_tool_parity.py` re-checks. A scripted peer gives the
//! recorded daemon replies. Every field is compared exactly, except that a
//! successful result's text content is compared as parsed JSON: it is the
//! structured result printed by Python's `json.dumps`, whose key order and
//! spacing are presentation.

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
fn comparable(mut reply: Value) -> Value {
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
        if comparable(reply.clone()) != comparable(case["reply"].clone()) {
            failures.push(format!("{}: replied {reply}", case["tool"]));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
