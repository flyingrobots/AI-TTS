// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The MCP server on standard input and output (`ai-tts mcp`, or `ai-tts-mcp`).
//! It answers as the Python `ai-tts-mcp` does (`tests/fixtures/mcp_session.json`):
//! newline-delimited JSON-RPC 2.0, nothing else on stdout, and no reply to a
//! line that is not a JSON-RPC request.

use serde_json::{Map, Value, json};
use std::io::{BufRead, Write};
use std::path::Path;

/// `tools/list` of the Python server, checked by `tests/test_mcp_parity_table.py`.
const TOOLS: &str = include_str!("mcp_tools.json");
/// The Python package version that the Python server reports.
const SERVER_VERSION: &str = "0.2.0";
const LATEST: &str = "2025-11-25";
const SUPPORTED: [&str; 4] = ["2024-11-05", "2025-03-26", "2025-06-18", LATEST];
const INSTRUCTIONS: &str = "Always enqueue requested speech, including while playback is held. \
A held player still accepts and synthesizes speech; it spools audio until Resume.";

type Outcome = Result<Value, Value>;

fn invalid_params() -> Value {
    json!({"code": -32602, "message": "Invalid request parameters", "data": ""})
}

/// The protocol version, when `params` form a valid `initialize` request.
fn requested_version(params: Option<&Value>) -> Option<&str> {
    let params = params?.as_object()?;
    let client = params.get("clientInfo")?.as_object()?;
    let named = ["name", "version"]
        .iter()
        .all(|key| client.get(*key).is_some_and(Value::is_string));
    (params.get("capabilities")?.is_object() && named)
        .then(|| params.get("protocolVersion")?.as_str())
        .flatten()
}

fn initialize(params: Option<&Value>) -> Outcome {
    let requested = requested_version(params).ok_or_else(invalid_params)?;
    let version = if SUPPORTED.contains(&requested) {
        requested
    } else {
        LATEST
    };
    Ok(json!({
        "capabilities": {
            "experimental": {},
            "prompts": {"listChanged": false},
            "resources": {"listChanged": false, "subscribe": false},
            "tools": {"listChanged": false},
        },
        "instructions": INSTRUCTIONS,
        "protocolVersion": version,
        "serverInfo": {
            "description": "Queue local speech and control serialized playback.",
            "name": "ai-tts",
            "title": "AI-TTS",
            "version": SERVER_VERSION,
        },
    }))
}

/// One server connection: whether `initialize` has succeeded.
struct Session<'socket> {
    initialized: bool,
    #[allow(
        dead_code,
        reason = "tool calls use the daemon socket in part 2 of #139"
    )]
    socket: &'socket Path,
}

impl Session<'_> {
    fn answer(&mut self, method: &str, params: Option<&Value>) -> Outcome {
        match method {
            "initialize" => {
                let result = initialize(params)?;
                self.initialized = true;
                Ok(result)
            }
            "ping" => Ok(json!({})),
            "tools/list"
            | "prompts/list"
            | "resources/list"
            | "resources/templates/list"
            | "tools/call"
                if !self.initialized =>
            {
                Err(invalid_params())
            }
            "tools/list" => serde_json::from_str::<Value>(TOOLS)
                .map(|tools| json!({"tools": tools}))
                .map_err(|_| json!({"code": -32603, "message": "Internal error", "data": ""})),
            "prompts/list" => Ok(json!({"prompts": []})),
            "resources/list" => Ok(json!({"resources": []})),
            "resources/templates/list" => Ok(json!({"resourceTemplates": []})),
            "tools/call" => {
                let tool = params
                    .and_then(|params| params.get("name"))
                    .and_then(Value::as_str)
                    .ok_or_else(invalid_params)?;
                let catalog: Vec<Value> = serde_json::from_str(TOOLS).unwrap_or_default();
                let arguments = params.and_then(|params| params.get("arguments"));
                Ok(crate::mcp_tools::call(
                    tool,
                    arguments,
                    &catalog,
                    self.socket,
                ))
            }
            other => Err(json!({"code": -32601, "message": "Method not found", "data": other})),
        }
    }

    /// The reply to one input line, or `None` when it is not a request.
    fn reply(&mut self, line: &str) -> Option<Value> {
        let message: Map<String, Value> = serde_json::from_str(line).ok()?;
        if message.get("jsonrpc")? != "2.0" {
            return None;
        }
        let method = message.get("method")?.as_str()?;
        let id = message
            .get("id")
            .filter(|id| id.is_string() || id.is_number())?;
        Some(match self.answer(method, message.get("params")) {
            Ok(result) => json!({"jsonrpc": "2.0", "id": id, "result": result}),
            Err(error) => json!({"jsonrpc": "2.0", "id": id, "error": error}),
        })
    }
}

/// Serve newline-delimited JSON-RPC from `input` until it ends.
pub fn serve(input: &mut dyn BufRead, output: &mut dyn Write, socket: &Path) {
    let mut session = Session {
        initialized: false,
        socket,
    };
    let mut bytes = Vec::new();
    loop {
        bytes.clear();
        match input.read_until(b'\n', &mut bytes) {
            Ok(0) | Err(_) => return,
            Ok(_) => {}
        }
        // A line that is not UTF-8 is not JSON, so it gets no reply.
        let line = String::from_utf8_lossy(&bytes);
        if let Some(reply) = session.reply(line.trim_end_matches(['\n', '\r'])) {
            let written = writeln!(output, "{reply}").and_then(|()| output.flush());
            if written.is_err() {
                // The host closed stdout; nobody remains to answer.
                return;
            }
        }
    }
}
