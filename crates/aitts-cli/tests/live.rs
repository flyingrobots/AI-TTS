// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary files, loopback Unix sockets, daemon threads).
//! The client against the real `aitts-daemon` serving the Python-written
//! `golden.db`. Oracle: the daemon's own reply line to the same request, sent
//! on a raw socket, which the Python CLI prints unchanged (`json.dumps`).

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

use aitts_daemon::{Config, EngineView, Running, StopOutcome};
use aitts_protocol::vocabulary::ModelState;
use serde_json::{Value, json};
use support::{run, same_json};

fn start(dir: &Path) -> Running {
    let database = dir.join("ai-tts.db");
    let fixture = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../aitts-store/tests/fixtures/golden.db"
    );
    std::fs::copy(fixture, &database).unwrap();
    aitts_daemon::start(Config {
        socket: dir.join("ai-tts.sock"),
        database,
        cache_dir: dir.join("cache"),
        engine: EngineView {
            name: "kokoro".to_owned(),
            voices: vec!["af_heart".to_owned()],
            is_local: true,
            state: ModelState::Cold,
        },
    })
    .unwrap()
}

fn raw(socket: &Path, request: &Value) -> Value {
    let mut stream = UnixStream::connect(socket).unwrap();
    stream.write_all(format!("{request}\n").as_bytes()).unwrap();
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line).unwrap();
    serde_json::from_str(&line).unwrap()
}

/// Golden table: (argv, the request the Python CLI sends for it, exit status).
fn table() -> Vec<(Vec<&'static str>, Value, u8)> {
    vec![
        (vec!["status"], json!({"op": "status"}), 0),
        (vec!["voices"], json!({"op": "voices"}), 0),
        (vec!["settings"], json!({"op": "settings"}), 0),
        (
            vec!["list", "input"],
            json!({"op": "list", "queue": "input"}),
            0,
        ),
        (
            vec!["list", "playback"],
            json!({"op": "list", "queue": "playback"}),
            0,
        ),
        (
            vec!["history", "--limit", "2"],
            json!({"op": "history", "limit": 2}),
            0,
        ),
        (
            vec!["get", "utt_0001"],
            json!({"op": "get", "id": "utt_0001"}),
            0,
        ),
        (
            vec!["get", "no-such-id"],
            json!({"op": "get", "id": "no-such-id"}),
            1,
        ),
    ]
}

#[test]
fn each_command_prints_the_daemon_reply_and_its_exit_status() {
    let dir = tempfile::tempdir().unwrap();
    let daemon = start(dir.path());
    for (argv, request, status) in table() {
        let expected = raw(daemon.socket(), &request);
        let outcome = run(daemon.socket(), &argv);
        assert_eq!(outcome.status, status, "{argv:?} exit status");
        assert!(
            same_json(&outcome.json(), &expected),
            "{argv:?} printed {} but the daemon replied {expected}",
            String::from_utf8_lossy(&outcome.stdout)
        );
    }
    assert_eq!(daemon.stop(Duration::from_secs(5)), StopOutcome::Clean);
}

#[test]
fn no_daemon_exits_two_with_an_unreachable_error() {
    let dir = tempfile::tempdir().unwrap();
    let outcome = run(&dir.path().join("absent.sock"), &["status"]);
    assert_eq!(outcome.status, 2);
    let printed = outcome.json();
    assert_eq!(printed["ok"], json!(false));
    assert_eq!(printed["error"]["type"], json!("unreachable"));
}
