// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (child processes, temporary directory).
//! Oracle: issue #138 scope and the install layout in the README: the Rust
//! `ai-tts` runs every client command itself, and hands `daemon` and `tui` to
//! the Python `ai-tts-py` installed beside it, with the same arguments.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

/// A tool directory holding a copy of the binary and a stand-in `ai-tts-py`
/// that records its arguments, one per line, and exits 7.
fn layout(dir: &Path) -> PathBuf {
    let bin = dir.join("bin");
    std::fs::create_dir(&bin).unwrap();
    std::fs::copy(env!("CARGO_BIN_EXE_ai-tts"), bin.join("ai-tts")).unwrap();
    let python = bin.join("ai-tts-py");
    let record = dir.join("python-argv");
    std::fs::write(
        &python,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\nexit 7\n",
            record.display()
        ),
    )
    .unwrap();
    std::fs::set_permissions(&python, std::fs::Permissions::from_mode(0o755)).unwrap();
    bin
}

/// Run the copied `ai-tts`; return its exit status and the arguments
/// `ai-tts-py` received, if it ran.
fn reach(dir: &Path, bin: &Path, args: &[&str]) -> (Option<i32>, Option<Vec<String>>) {
    let record = dir.join("python-argv");
    let _ = std::fs::remove_file(&record);
    let status = Command::new(bin.join("ai-tts"))
        .env_clear()
        .env("AI_TTS_SOCKET", dir.join("absent.sock"))
        .args(args)
        .status()
        .unwrap();
    let seen = std::fs::read_to_string(&record)
        .ok()
        .map(|text| text.lines().map(str::to_owned).collect());
    (status.code(), seen)
}

#[test]
fn daemon_and_tui_reach_ai_tts_py_with_their_arguments_and_status() {
    let dir = tempfile::tempdir().unwrap();
    let bin = layout(dir.path());
    let cases: [&[&str]; 4] = [
        &["daemon", "--log-file", "/tmp/x.log"],
        &["--socket", "/tmp/s.sock", "daemon", "--workers", "1"],
        &["--socket=/tmp/s.sock", "tui"],
        &["tui"],
    ];
    for args in cases {
        let (status, seen) = reach(dir.path(), &bin, args);
        let expected: Vec<String> = args.iter().map(|arg| (*arg).to_owned()).collect();
        assert_eq!((status, seen), (Some(7), Some(expected)), "{args:?}");
    }
}

#[test]
fn client_commands_stay_in_the_rust_binary() {
    let dir = tempfile::tempdir().unwrap();
    let bin = layout(dir.path());
    for args in [
        &["status"][..],
        &["say", "daemon"],
        &["get", "tui"],
        &["--help"],
    ] {
        let (status, seen) = reach(dir.path(), &bin, args);
        assert_eq!(seen, None, "{args:?} reached ai-tts-py");
        assert!(matches!(status, Some(0 | 2)), "{args:?} exit {status:?}");
    }
}

#[test]
fn daemon_without_ai_tts_py_exits_one() {
    let dir = tempfile::tempdir().unwrap();
    let bin = dir.path().join("bin");
    std::fs::create_dir(&bin).unwrap();
    std::fs::copy(env!("CARGO_BIN_EXE_ai-tts"), bin.join("ai-tts")).unwrap();
    let (status, _) = reach(dir.path(), &bin, &["daemon"]);
    assert_eq!(status, Some(1));
}
