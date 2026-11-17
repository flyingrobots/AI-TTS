// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (child processes, owned temporary files, a loopback Unix socket).
//! Oracle: issue #143 and `docs/testing-evidence/2026-09-03-single-instance.md`: a
//! second `ai-ttsd` refuses to start, and a stop signal ends the process in time.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// The bounded stop the daemon promises, plus process start and exit overhead.
const STOP_LIMIT: Duration = Duration::from_secs(5);

fn daemon(home: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_ai-ttsd"));
    command
        .env_clear()
        .env("AI_TTS_HOME", home)
        .env("AI_TTS_SOCKET", home.join("ai-tts.sock"))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    command
}

fn wait_for_socket(home: &Path, child: &mut Child) {
    let deadline = Instant::now() + Duration::from_secs(10);
    while !home.join("ai-tts.sock").exists() {
        assert!(
            child.try_wait().unwrap().is_none(),
            "the daemon exited before serving"
        );
        assert!(
            Instant::now() < deadline,
            "the daemon did not bind its socket"
        );
        std::thread::yield_now();
    }
}

fn wait_with_limit(child: &mut Child, limit: Duration) -> Option<std::process::ExitStatus> {
    let deadline = Instant::now() + limit;
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            return Some(status);
        }
        if Instant::now() >= deadline {
            return None;
        }
        std::thread::yield_now();
    }
}

fn signal(child: &Child, name: &str) {
    let sent = Command::new("kill")
        .arg(format!("-{name}"))
        .arg(child.id().to_string())
        .status()
        .unwrap();
    assert!(sent.success());
}

#[test]
fn a_term_signal_ends_the_process_in_time_and_removes_the_socket() {
    let home = tempfile::tempdir().unwrap();
    let mut child = daemon(home.path()).spawn().unwrap();
    wait_for_socket(home.path(), &mut child);
    signal(&child, "TERM");
    let status = wait_with_limit(&mut child, STOP_LIMIT);
    if status.is_none() {
        child.kill().unwrap();
    }
    assert!(status.is_some_and(|status| status.success()), "{status:?}");
    assert!(!home.path().join("ai-tts.sock").exists());
}

#[test]
fn a_second_process_refuses_to_start_while_the_first_runs() {
    let home = tempfile::tempdir().unwrap();
    let mut first = daemon(home.path()).spawn().unwrap();
    wait_for_socket(home.path(), &mut first);
    let second = daemon(home.path()).output().unwrap();
    signal(&first, "TERM");
    let _ = wait_with_limit(&mut first, STOP_LIMIT);
    let _ = first.kill();
    assert!(!second.status.success());
    assert!(
        String::from_utf8_lossy(&second.stderr).contains("already"),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
}
