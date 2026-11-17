// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (one child process, temporary directory).
//! Oracle: the exit-status contract in `docs/design/features.md` section 8 and
//! the socket rule of `aitts.paths.default_socket` (`AI_TTS_SOCKET`, then
//! `AI_TTS_HOME/ai-tts.sock`).

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

mod support;

use std::process::Command;
use support::{REFUSAL, Recorder};

#[test]
fn the_binary_runs_without_python_and_honours_ai_tts_socket() {
    let peer = Recorder::start();
    let output = Command::new(env!("CARGO_BIN_EXE_ai-tts"))
        .env_clear()
        .env("AI_TTS_SOCKET", &peer.socket)
        .args(["get", "u-1"])
        .output()
        .unwrap();
    let sent = peer.finish();
    assert_eq!(sent, vec![serde_json::json!({"op": "get", "id": "u-1"})]);
    assert_eq!(output.status.code(), Some(1));
    let printed: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        printed,
        serde_json::from_str::<serde_json::Value>(REFUSAL).unwrap()
    );
}

#[test]
fn ai_tts_home_chooses_the_socket_when_ai_tts_socket_is_unset() {
    let peer = Recorder::start();
    let home = peer.socket.parent().unwrap().join("home");
    std::fs::create_dir(&home).unwrap();
    std::os::unix::fs::symlink(&peer.socket, home.join("ai-tts.sock")).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_ai-tts"))
        .env_clear()
        .env("AI_TTS_HOME", &home)
        .arg("status")
        .output()
        .unwrap();
    assert_eq!(peer.finish(), vec![serde_json::json!({"op": "status"})]);
    assert_eq!(output.status.code(), Some(1));
}
