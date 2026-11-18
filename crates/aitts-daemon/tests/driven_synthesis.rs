// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (a real worker subprocess, owned temporary files, a loopback
//! Unix socket and the daemon's threads).
//! The daemon drives synthesis ahead of playback through a sink.
//! Oracles: the `aitts-engine` fake worker (worker protocol 2, real argument
//! shape; the known stream is each text byte twice); the conductor contract
//! (a held queue does not play; a clip cancelled during synthesis is not played
//! and its audio is removed; a failed synthesis does not stop later clips).
//! Waits are on observable conditions with a deadline, never bare sleeps. The
//! cancel race is forced: the gate engine reports when it is reached and holds
//! the stream until the test opens it.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use aitts_artifacts::spool::Spool;
use aitts_daemon::driver::{Sink, Synthesis};
use aitts_daemon::{Config, EngineView};
use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::registry::Registry;
use aitts_engine::worker::{WorkerLaunch, WorkerSupervisor};
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::vocabulary::{ModelState, State};
use support::request;

const LIMIT: Duration = Duration::from_secs(20);

/// Every clip the sink played, with its PCM, in play order.
type Played = Arc<Mutex<Vec<(String, Vec<u8>)>>>;

struct RecordingSink(Played);
impl Sink for RecordingSink {
    fn play(&mut self, id: &str, mut spool: Spool) -> Result<(), String> {
        let mut pcm = Vec::new();
        loop {
            spool.fill();
            let read = spool.read(4096);
            pcm.extend(read.pcm);
            if read.complete || read.ended {
                break;
            }
        }
        self.0.lock().unwrap().push((id.to_owned(), pcm));
        Ok(())
    }
}

/// A runtime root whose `venv/bin/python` runs a copy of the fake worker.
fn runtime(mode: &str) -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    let bin = root.path().join("venv/bin");
    fs::create_dir_all(&bin).unwrap();
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../aitts-engine/tests/fixtures/fake_worker.py");
    fs::copy(fixture, bin.join("fake_worker.py")).unwrap();
    let python = bin.join("python");
    fs::write(
        &python,
        "#!/bin/sh\nexec python3 \"$(dirname \"$0\")/fake_worker.py\" \"$@\"\n",
    )
    .unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(root.path().join("mode"), mode).unwrap();
    root
}

fn worker(root: &Path) -> WorkerSupervisor {
    WorkerSupervisor::new(
        "fake",
        WorkerLaunch::python_runtime("fake", root),
        Duration::from_secs(10),
    )
}

/// Reports when it is reached (its spool exists), then holds the stream.
struct Gated {
    inner: WorkerSupervisor,
    gate: Receiver<()>,
    reached: Sender<()>,
}
impl Engine for Gated {
    fn name(&self) -> &str {
        self.inner.name()
    }
    fn stream(
        &mut self,
        request: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        let _unwatched = self.reached.send(());
        self.gate
            .recv()
            .map_err(|_| EngineError::Refused("gate dropped"))?;
        self.inner.stream(request, sink)
    }
    fn recover(&mut self) -> Result<(), EngineError> {
        self.inner.recover()
    }
}

struct Daemon {
    running: Option<aitts_daemon::Running>,
    socket: PathBuf,
    spools: PathBuf,
    played: Played,
    _dir: tempfile::TempDir,
}

impl Daemon {
    fn start(engine: Box<dyn Engine>) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let spools = dir.path().join("spools");
        fs::create_dir(&spools).unwrap();
        let config = Config {
            socket: dir.path().join("ai-tts.sock"),
            database: dir.path().join("queue.db"),
            cache_dir: dir.path().join("cache"),
            engine: EngineView {
                name: "fake".to_owned(),
                voices: vec!["bm_daniel".to_owned()],
                is_local: true,
                state: ModelState::Cold,
            },
        };
        let mut engines = Registry::default();
        assert!(engines.register(engine).is_ok());
        let played = Played::default();
        let synthesis = Synthesis {
            engines,
            spool_dir: spools.clone(),
            capacity_frames: 1024,
            sink: Box::new(RecordingSink(Arc::clone(&played))),
        };
        let socket = config.socket.clone();
        let running = aitts_daemon::start_with(config, synthesis).unwrap();
        Self {
            running: Some(running),
            socket,
            spools,
            played,
            _dir: dir,
        }
    }

    fn ask(&self, operation: Operation, line: &str) -> Reply {
        let reply = request(&self.socket, format!("{line}\n").as_bytes());
        decode_reply(operation, &reply).unwrap_or_else(|error| {
            panic!("{line} gave {} ({error})", String::from_utf8_lossy(&reply))
        })
    }

    fn submit(&self, text: &str) -> String {
        match self.ask(
            Operation::Submit,
            &format!(r#"{{"op":"submit","text":"{text}"}}"#),
        ) {
            Reply::Submit(submitted) => submitted.id,
            other => panic!("submit refused: {other:?}"),
        }
    }

    fn state(&self, id: &str) -> State {
        let Reply::Get(item) = self.ask(Operation::Get, &format!(r#"{{"op":"get","id":"{id}"}}"#))
        else {
            panic!("get {id} failed")
        };
        item.item.state
    }

    /// Wait, with a deadline, until `id` reaches `wanted`.
    fn wait_for(&self, id: &str, wanted: State) {
        let deadline = Instant::now() + LIMIT;
        loop {
            let state = self.state(id);
            if state == wanted {
                return;
            }
            assert!(
                Instant::now() < deadline,
                "{id} stayed {state:?}, expected {wanted:?}"
            );
            std::thread::yield_now();
        }
    }

    fn played(&self) -> Vec<(String, Vec<u8>)> {
        self.played.lock().unwrap().clone()
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        if let Some(running) = self.running.take() {
            let _outcome = running.stop(Duration::from_secs(5));
        }
    }
}

fn resume(daemon: &Daemon) {
    assert!(matches!(
        daemon.ask(Operation::Resume, r#"{"op":"resume"}"#),
        Reply::Resume(_)
    ));
}

#[test]
fn a_submitted_clip_is_synthesized_and_played_through_the_sink() {
    let root = runtime("golden");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    resume(&daemon);
    let id = daemon.submit("Hello there.");
    daemon.wait_for(&id, State::Played);
    assert_eq!(
        daemon.played(),
        [(id, "Hello there.".repeat(2).into_bytes())]
    );
}

#[test]
fn a_held_queue_synthesizes_but_plays_nothing_until_resume() {
    let root = runtime("golden");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    // A started daemon is held, as after any restart.
    let id = daemon.submit("Wait for me.");
    daemon.wait_for(&id, State::Ready);
    assert!(daemon.played().is_empty(), "a held queue played audio");
    resume(&daemon);
    daemon.wait_for(&id, State::Played);
}

#[test]
fn a_clip_cancelled_during_synthesis_is_not_played_and_leaves_no_audio() {
    let root = runtime("golden");
    let (open, gate) = channel();
    let (reached, engine_reached) = channel();
    let daemon = Daemon::start(Box::new(Gated {
        inner: worker(root.path()),
        gate,
        reached,
    }));
    resume(&daemon);
    let id = daemon.submit("Never mind.");
    engine_reached.recv_timeout(LIMIT).unwrap();
    assert!(matches!(
        daemon.ask(
            Operation::Cancel,
            &format!(r#"{{"op":"cancel","id":"{id}"}}"#)
        ),
        Reply::Cancel(_)
    ));
    open.send(()).unwrap();
    // The spool existed when the engine was reached; wait for its removal.
    let spool = daemon.spools.join(format!("{id}.wav"));
    let deadline = Instant::now() + LIMIT;
    while spool.exists() {
        assert!(
            Instant::now() < deadline,
            "the cancelled clip's audio was not removed"
        );
        std::thread::yield_now();
    }
    assert_eq!(daemon.state(&id), State::Cancelled);
    assert!(daemon.played().is_empty(), "a cancelled clip was played");
}

#[test]
fn a_failed_synthesis_does_not_stop_later_clips() {
    let root = runtime("random 5 exit");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    resume(&daemon);
    let failed = daemon.submit("This fails.");
    daemon.wait_for(&failed, State::Failed);
    fs::write(root.path().join("mode"), "golden").unwrap();
    let next = daemon.submit("This plays.");
    daemon.wait_for(&next, State::Played);
    assert_eq!(
        daemon.played(),
        [(next, "This plays.".repeat(2).into_bytes())]
    );
}

#[test]
fn the_discarding_sink_accepts_a_sealed_spool() {
    use aitts_daemon::driver::DiscardingSink;
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&dir.path().join("a.wav"), 1).unwrap();
    spool.append(&[1, 0, 2, 0, 3, 0]).unwrap();
    spool.seal().unwrap();
    spool.finish(None);
    assert_eq!(DiscardingSink.play("a", spool), Ok(()));
}

#[test]
fn the_discarding_sink_reports_a_spool_that_ended_with_an_error() {
    use aitts_daemon::driver::DiscardingSink;
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&dir.path().join("a.wav"), 1).unwrap();
    spool.append(&[1, 0]).unwrap();
    spool.finish(Some("worker exited".to_owned()));
    assert!(
        DiscardingSink.play("a", spool).is_err(),
        "a failed spool played as complete"
    );
}
