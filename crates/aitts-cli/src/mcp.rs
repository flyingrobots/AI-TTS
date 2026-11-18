// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The MCP server on standard input and output (`ai-tts mcp`).

use std::io::{BufRead, Write};
use std::path::Path;

/// Serve newline-delimited JSON-RPC from `input` until it ends.
#[allow(clippy::todo, reason = "RED stub")]
pub fn serve(_input: &mut dyn BufRead, _output: &mut dyn Write, _socket: &Path) {
    todo!()
}
