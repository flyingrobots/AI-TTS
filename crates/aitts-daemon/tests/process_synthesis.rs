// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (child processes, owned temporary files, a loopback Unix socket).
//! The `ai-ttsd` binary drives synthesis when a Kokoro runtime is installed.
//! Oracles: Python `model_setup.installed_runtime` for what counts as installed;
//! the `aitts-engine` fake worker (worker protocol 2, real argument shape) as
//! the installed runtime's Python; the conductor contract (a resumed daemon
//! plays a submitted clip to Played). Waits are on observable states with a
//! deadline.

#![allow(clippy::unwrap_used, clippy::panic, reason = "test code fails loudly")]

mod support;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use aitts_engine::catalog::{WORKER_PROTOCOL_VERSION, pinned_digests};
use aitts_engine::installed::revision;
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::vocabulary::State;
use support::request;

const LIMIT: Duration = Duration::from_secs(20);

/// Install a complete Kokoro runtime whose Python is the fake worker.
fn install_kokoro(home: &Path) {
    let runtimes = home.join("model-runtimes");
    let root = runtimes.join("kokoro-test");
    fs::create_dir_all(root.join("venv/bin")).unwrap();
    fs::create_dir_all(root.join("adapter/aitts")).unwrap();
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../aitts-engine/tests/fixtures/fake_worker.py");
    fs::copy(fixture, root.join("venv/bin/fake_worker.py")).unwrap();
    let python = root.join("venv/bin/python");
    fs::write(
        &python,
        "#!/bin/sh\nexec python3 \"$(dirname \"$0\")/fake_worker.py\" \"$@\"\n",
    )
    .unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(root.join("adapter/aitts/model_worker.py"), "").unwrap();
    for file in pinned_digests("kokoro").unwrap().keys() {
        let path = root.join("assets").join(file);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, "").unwrap();
    }
    fs::write(root.join("mode"), "golden").unwrap();
    let manifest = serde_json::json!({
        "directory": "kokoro-test",
        "revision": revision("kokoro").unwrap(),
        "worker_protocol": WORKER_PROTOCOL_VERSION,
    });
    fs::write(runtimes.join("kokoro.json"), manifest.to_string()).unwrap();
}

struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = Command::new("kill")
            .arg("-TERM")
            .arg(self.0.id().to_string())
            .status();
        let _ = self.0.wait();
    }
}

fn start(home: &Path) -> Process {
    let child = Command::new(env!("CARGO_BIN_EXE_ai-ttsd"))
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap_or_default())
        .env("AI_TTS_HOME", home)
        .env("AI_TTS_SOCKET", home.join("ai-tts.sock"))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut process = Process(child);
    let deadline = Instant::now() + LIMIT;
    // The socket file appears at bind, before listen: wait until it accepts.
    while UnixStream::connect(home.join("ai-tts.sock")).is_err() {
        assert!(
            process.0.try_wait().unwrap().is_none(),
            "ai-ttsd exited before serving"
        );
        assert!(Instant::now() < deadline, "ai-ttsd did not bind its socket");
        std::thread::yield_now();
    }
    process
}

fn ask(home: &Path, operation: Operation, line: &str) -> Reply {
    let reply = request(&home.join("ai-tts.sock"), format!("{line}\n").as_bytes());
    decode_reply(operation, &reply)
        .unwrap_or_else(|error| panic!("{line} gave {} ({error})", String::from_utf8_lossy(&reply)))
}

/// Resume, submit one clip, and wait until it reaches `wanted`.
fn submit_and_wait(home: &Path, wanted: State) {
    assert!(matches!(
        ask(home, Operation::Resume, r#"{"op":"resume"}"#),
        Reply::Resume(_)
    ));
    let Reply::Submit(submitted) = ask(
        home,
        Operation::Submit,
        r#"{"op":"submit","text":"Hello."}"#,
    ) else {
        panic!("submit was refused")
    };
    let get = format!(r#"{{"op":"get","id":"{}"}}"#, submitted.id);
    let deadline = Instant::now() + LIMIT;
    loop {
        let Reply::Get(item) = ask(home, Operation::Get, &get) else {
            panic!("get failed")
        };
        if item.item.state == wanted {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "the clip stayed {:?}, expected {wanted:?}",
            item.item.state
        );
        std::thread::yield_now();
    }
}

#[test]
fn an_installed_kokoro_runtime_plays_a_submitted_clip() {
    let home = tempfile::tempdir().unwrap();
    install_kokoro(home.path());
    let _daemon = start(home.path());
    submit_and_wait(home.path(), State::Played);
}

#[test]
fn without_an_installed_runtime_a_submitted_clip_fails_and_the_daemon_serves() {
    // As Python's managed engine: the voices stay listed, and synthesis fails
    // with the model-setup instruction.
    let home = tempfile::tempdir().unwrap();
    let _daemon = start(home.path());
    submit_and_wait(home.path(), State::Failed);
    assert!(matches!(
        ask(home.path(), Operation::Status, r#"{"op":"status"}"#),
        Reply::Status(_)
    ));
}
