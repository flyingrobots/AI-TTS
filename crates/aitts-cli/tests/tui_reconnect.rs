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
    std::thread::scope(|scope| {
        scope.spawn(|| {
            watch(&socket, &inputs, &stop, &|| {
                let _ = wait_for_restart.lock().unwrap().recv();
            });
        });
        let Input::Connected(snapshot) = next(&received) else {
            panic!("not connected first")
        };
        assert!(snapshot.get("plan").is_some(), "a snapshot: {snapshot}");
        assert_eq!(first.stop(Duration::from_secs(5)), StopOutcome::Clean);
        assert!(
            matches!(next(&received), Input::Disconnected(_)),
            "no disconnect report"
        );
        let second = start(dir.path());
        restarted.send(()).unwrap();
        assert!(
            matches!(next(&received), Input::Connected(_)),
            "not connected again"
        );
        stop.store(true, Ordering::SeqCst);
        restarted.send(()).ok();
        drop(received);
        assert_eq!(second.stop(Duration::from_secs(5)), StopOutcome::Clean);
    });
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
