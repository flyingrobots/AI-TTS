// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (temporary files, loopback Unix sockets, daemon threads).
//! Oracle: issue #140 ("the dashboard connects again after the daemon
//! restarts") and the Python dashboard's loop (subscribe, read a snapshot,
//! report a failure, retry). The real `aitts-daemon` is stopped and started on
//! the same socket. Order is forced: the watcher's `wait` blocks until the
//! test has started the new daemon, so nothing depends on timing.

#![allow(clippy::unwrap_used, clippy::panic, reason = "test code fails loudly")]

use aitts_cli::tui::{Input, watch};
use aitts_daemon::{Config, EngineView, Running, StopOutcome};
use aitts_protocol::vocabulary::ModelState;
use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, channel};
use std::time::Duration;

const LIMIT: Duration = Duration::from_secs(10);

fn start(dir: &Path) -> Running {
    let database = dir.join("ai-tts.db");
    if !database.exists() {
        let fixture = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../aitts-store/tests/fixtures/golden.db"
        );
        std::fs::copy(fixture, &database).unwrap();
    }
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

fn next(inputs: &Receiver<Input>) -> Input {
    inputs
        .recv_timeout(LIMIT)
        .unwrap_or_else(|error| panic!("no input: {error}"))
}

#[test]
fn the_watcher_reports_a_restart_and_connects_again() {
    let dir = tempfile::tempdir().unwrap();
    let socket = dir.path().join("ai-tts.sock");
    let first = start(dir.path());
    let (inputs, received) = channel();
    let (restarted, wait_for_restart) = channel::<()>();
    let wait_for_restart = Mutex::new(wait_for_restart);
    let stop = AtomicBool::new(false);
    let second = std::thread::scope(|scope| {
        scope.spawn(|| {
            watch(&socket, &inputs, &stop, &|| {
                // A closed channel means the test ended or failed: stop watching.
                if wait_for_restart.lock().unwrap().recv().is_err() {
                    stop.store(true, Ordering::SeqCst);
                }
            });
        });
        // Owned here, so a failing assertion drops both and the watcher ends.
        let (restarted, received) = (restarted, received);
        let Input::Connected(snapshot) = next(&received) else {
            panic!("not connected first")
        };
        assert!(snapshot.get("plan").is_some(), "a snapshot: {snapshot}");
        assert_eq!(first.stop(Duration::from_secs(5)), StopOutcome::Clean);
        let reported = next(&received);
        assert!(
            matches!(reported, Input::Disconnected(_)),
            "no disconnect report: {reported:?}"
        );
        let second = start(dir.path());
        restarted.send(()).unwrap();
        let again = next(&received);
        stop.store(true, Ordering::SeqCst);
        assert!(
            matches!(again, Input::Connected(_)),
            "not connected again: {again:?}"
        );
        second
    });
    assert_eq!(second.stop(Duration::from_secs(5)), StopOutcome::Clean);
}

/// The watcher asks for playback progress, as the Python dashboard does, so
/// the meter and position move. A recording peer checks the request.
#[test]
fn the_watcher_subscribes_with_playback_progress() {
    use std::io::{BufRead, BufReader, Write};
    let dir = tempfile::tempdir().unwrap();
    let socket = dir.path().join("peer.sock");
    let listener = std::os::unix::net::UnixListener::bind(&socket).unwrap();
    let (inputs, received) = channel();
    let stop = AtomicBool::new(false);
    let request = std::thread::scope(|scope| {
        scope.spawn(|| {
            watch(&socket, &inputs, &stop, &|| {
                stop.store(true, Ordering::SeqCst);
            });
        });
        let (stream, _) = listener.accept().unwrap();
        let mut line = String::new();
        BufReader::new(&stream).read_line(&mut line).unwrap();
        (&stream)
            .write_all(b"{\"ok\":true,\"subscribed\":true}\n")
            .unwrap();
        // The snapshot request is refused; the watcher reports it and stops.
        let (refused, _) = listener.accept().unwrap();
        BufReader::new(&refused)
            .read_line(&mut String::new())
            .unwrap();
        (&refused)
            .write_all(b"{\"ok\":false,\"error\":{\"type\":\"internal\",\"message\":\"no\"}}\n")
            .unwrap();
        assert!(matches!(next(&received), Input::Disconnected(_)));
        line
    });
    let request: serde_json::Value = serde_json::from_str(&request).unwrap();
    assert_eq!(
        request,
        serde_json::json!({"op": "subscribe", "playback_progress": true})
    );
}
#[test]
fn no_daemon_reports_disconnected_and_waits() {
    let dir = tempfile::tempdir().unwrap();
    let (inputs, received) = channel();
    let stop = AtomicBool::new(false);
    std::thread::scope(|scope| {
        scope.spawn(|| {
            watch(&dir.path().join("absent.sock"), &inputs, &stop, &|| {
                stop.store(true, Ordering::SeqCst);
            });
        });
        assert!(matches!(next(&received), Input::Disconnected(_)));
    });
}
