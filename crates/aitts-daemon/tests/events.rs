// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files, a loopback Unix socket, the daemon's
//! threads and, in one test, the fake worker subprocess).
//! Events a subscriber receives for queue operations and for driven clips.
//! Oracles: Python `_announce_admission`, `_on_transition`, `_op_reorder` and
//! `VoiceRegistry.resolve` (`voice_assigned` before the admission), read as the
//! specification; event times must equal the store's own stamps, read through
//! a separate connection. Every line must decode through `decode_event`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::Duration;

use aitts_daemon::driver::{DiscardingSink, Synthesis};
use aitts_daemon::{Config, EngineView};
use aitts_engine::registry::Registry;
use aitts_engine::worker::{WorkerLaunch, WorkerSupervisor};
use aitts_protocol::catalog::Assignment;
use aitts_protocol::event::{Event, decode_event};
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::value::{Nullable, Number};
use aitts_protocol::vocabulary::{ModelState, State};
use aitts_store::{Store, SystemClock};
use support::{read_line, request};

struct Daemon {
    running: Option<aitts_daemon::Running>,
    socket: PathBuf,
    database: PathBuf,
    _dir: tempfile::TempDir,
    _runtime: Option<tempfile::TempDir>,
}

fn config(dir: &Path) -> Config {
    Config {
        socket: dir.join("ai-tts.sock"),
        database: dir.join("queue.db"),
        cache_dir: dir.join("cache"),
        engine: EngineView {
            name: "fake".to_owned(),
            voices: vec!["bm_daniel".to_owned()],
            is_local: true,
            state: ModelState::Cold,
        },
    }
}

impl Daemon {
    fn start() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let config = config(dir.path());
        let (socket, database) = (config.socket.clone(), config.database.clone());
        Self {
            running: Some(aitts_daemon::start(config).unwrap()),
            socket,
            database,
            _dir: dir,
            _runtime: None,
        }
    }

    fn start_driven() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        let bin = root.path().join("venv/bin");
        fs::create_dir_all(&bin).unwrap();
        fs::copy(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../aitts-engine/tests/fixtures/fake_worker.py"),
            bin.join("fake_worker.py"),
        )
        .unwrap();
        fs::write(
            bin.join("python"),
            "#!/bin/sh\nexec python3 \"$(dirname \"$0\")/fake_worker.py\" \"$@\"\n",
        )
        .unwrap();
        fs::set_permissions(bin.join("python"), fs::Permissions::from_mode(0o755)).unwrap();
        fs::write(root.path().join("mode"), "golden").unwrap();
        let spools = dir.path().join("spools");
        fs::create_dir(&spools).unwrap();
        let mut engines = Registry::default();
        let worker = WorkerSupervisor::new(
            "fake",
            WorkerLaunch::python_runtime("fake", root.path()),
            Duration::from_secs(10),
        );
        assert!(engines.register(Box::new(worker)).is_ok());
        let synthesis = Synthesis {
            engines,
            spool_dir: spools,
            capacity_frames: 1024,
            sink: Box::new(DiscardingSink),
            retry_after: Duration::from_millis(5),
            on_idle: None,
        };
        let config = config(dir.path());
        let (socket, database) = (config.socket.clone(), config.database.clone());
        let running = aitts_daemon::start_with(config, synthesis).unwrap();
        Self {
            running: Some(running),
            socket,
            database,
            _dir: dir,
            _runtime: Some(root),
        }
    }

    fn subscribe(&self) -> UnixStream {
        let stream = UnixStream::connect(&self.socket).unwrap();
        (&stream).write_all(b"{\"op\":\"subscribe\"}\n").unwrap();
        assert!(
            !read_line(&stream).is_empty(),
            "no subscribe acknowledgement"
        );
        stream
    }

    fn ask(&self, operation: Operation, line: &str) -> Reply {
        let reply = request(&self.socket, format!("{line}\n").as_bytes());
        decode_reply(operation, &reply).unwrap_or_else(|error| {
            panic!("{line} gave {} ({error})", String::from_utf8_lossy(&reply))
        })
    }

    fn submit(&self, line: &str) -> String {
        match self.ask(Operation::Submit, line) {
            Reply::Submit(submitted) => submitted.id,
            other => panic!("{line} refused: {other:?}"),
        }
    }

    fn store(&self) -> Store {
        Store::open(&self.database, SystemClock).unwrap()
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        if let Some(running) = self.running.take() {
            let _outcome = running.stop(Duration::from_secs(5));
        }
    }
}

fn next_event(stream: &UnixStream) -> Event {
    let line = read_line(stream);
    decode_event(&line).unwrap_or_else(|error| {
        panic!(
            "{} is not an event ({error})",
            String::from_utf8_lossy(&line)
        )
    })
}

fn number(value: f64) -> Number {
    Number::from_f64(value).unwrap()
}

fn changed(id: &str, from: Option<State>, to: State, at: f64) -> Event {
    Event::StateChanged {
        id: id.to_owned(),
        from: from.map_or(Nullable::Null, Nullable::Value),
        to,
        at: number(at),
    }
}

#[test]
fn queue_operations_send_the_python_events_in_order() {
    let daemon = Daemon::start();
    let events = daemon.subscribe();
    let a = daemon.submit(r#"{"op":"submit","text":"First."}"#);
    let agent = daemon.submit(r#"{"op":"submit","text":"Mine.","source":"agent-x"}"#);
    assert!(matches!(
        daemon.ask(
            Operation::Cancel,
            &format!(r#"{{"op":"cancel","id":"{a}"}}"#)
        ),
        Reply::Cancel(_)
    ));
    let c = daemon.submit(r#"{"op":"submit","text":"Last."}"#);
    let line = format!(r#"{{"op":"reorder","ids":["{c}","{agent}"]}}"#);
    assert!(matches!(
        daemon.ask(Operation::Reorder, &line),
        Reply::Reorder(_)
    ));
    let store = daemon.store();
    let row = |id: &str| store.queue().get(id).unwrap().unwrap();
    let claim = store.voices().get("agent-x").unwrap().unwrap();
    let expected = [
        changed(&a, None, State::Queued, row(&a).submitted_at),
        Event::VoiceAssigned {
            assignment: Assignment {
                source: "agent-x".to_owned(),
                voice: "bm_daniel".to_owned(),
                pinned: false,
                assigned_at: number(claim.assigned_at),
            },
        },
        changed(&agent, None, State::Queued, row(&agent).submitted_at),
        changed(
            &a,
            Some(State::Queued),
            State::Cancelled,
            row(&a).state_changed_at,
        ),
        changed(&c, None, State::Queued, row(&c).submitted_at),
        Event::PlanReordered {
            ids: vec![c.clone(), agent.clone()],
        },
    ];
    for (index, wanted) in expected.into_iter().enumerate() {
        assert_eq!(next_event(&events), wanted, "event {index}");
    }
}

#[test]
fn a_driven_clip_announces_each_transition_in_order() {
    use State::{Played, Playing, Queued, Ready, Synthesizing};
    let daemon = Daemon::start_driven();
    assert!(matches!(
        daemon.ask(Operation::Resume, r#"{"op":"resume"}"#),
        Reply::Resume(_)
    ));
    let events = daemon.subscribe();
    let id = daemon.submit(r#"{"op":"submit","text":"Watch me."}"#);
    let steps: Vec<(Nullable<State>, State)> = (0..5)
        .map(|_| match next_event(&events) {
            Event::StateChanged {
                id: seen, from, to, ..
            } if seen == id => (from, to),
            other => panic!("unexpected event {other:?}"),
        })
        .collect();
    assert_eq!(
        steps,
        [
            (Nullable::Null, Queued),
            (Nullable::Value(Queued), Synthesizing),
            (Nullable::Value(Synthesizing), Ready),
            (Nullable::Value(Ready), Playing),
            (Nullable::Value(Playing), Played),
        ]
    );
}
