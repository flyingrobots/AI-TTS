// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (child processes, temporary directory).
//! Oracle: MCP stdio transport (stdout carries newline-delimited JSON-RPC only)
//! and issue #139: `ai-tts mcp` serves MCP, and `ai-tts-mcp` is a name that starts it.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

use serde_json::{Value, json};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

const SESSION: &str = concat!(
    r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}"#,
    "\n",
    r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#,
    "\nnot json\n",
    r#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#,
    "\n"
);

fn session(program: &Path, args: &[&str]) -> (Option<i32>, Vec<Value>) {
    let mut child = Command::new(program)
        .env_clear()
        .env("AI_TTS_SOCKET", "/nonexistent/ai-tts.sock")
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(SESSION.as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.ends_with('\n'), "stdout ends without a newline");
    let lines = text
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    (output.status.code(), lines)
}

fn ids(replies: &[Value]) -> Vec<Value> {
    replies.iter().map(|reply| reply["id"].clone()).collect()
}

#[test]
fn ai_tts_mcp_writes_only_json_rpc_replies_on_stdout() {
    let (status, replies) = session(Path::new(env!("CARGO_BIN_EXE_ai-tts")), &["mcp"]);
    assert_eq!(status, Some(0));
    assert_eq!(ids(&replies), [json!(1), json!(2)]);
    assert_eq!(replies[1]["result"]["tools"].as_array().unwrap().len(), 21);
}

#[test]
fn the_name_ai_tts_mcp_starts_the_same_server() {
    let dir = tempfile::tempdir().unwrap();
    let alias = dir.path().join("ai-tts-mcp");
    std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_ai-tts"), &alias).unwrap();
    let (status, replies) = session(&alias, &[]);
    assert_eq!(status, Some(0));
    assert_eq!(ids(&replies), [json!(1), json!(2)]);
}
