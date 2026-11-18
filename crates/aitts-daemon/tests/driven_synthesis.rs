// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (a real worker subprocess, owned temporary files, a loopback
//! Unix socket and the daemon's threads).
//! The daemon drives synthesis ahead of playback through a sink.
//! Oracles: the `aitts-engine` fake worker (worker protocol 2, real argument
//! shape; the known stream is each text byte twice); the conductor contract (a
//! held queue does not play; audio that is no longer owed is removed; a failed
//! synthesis does not stop later clips; a report the ledger did not record is
//! retried; the device is released when its clip ends); the daemon start and
//! stop contract.
//! Interleavings are forced, never raced: gate engines and gate sinks report
//! when they are reached and wait for the test; the driver's idle signal is the
//! checkpoint that a planning turn ran. Waits are on observable conditions with
//! a deadline. Where a test must not wake the driver, it observes the store
//! through its own connection instead of the socket.

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
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use aitts_artifacts::spool::{Spool, SpoolStorage};
use aitts_daemon::driver::{DiscardingSink, Sink, Synthesis};
use aitts_daemon::{Config, EngineView, StartError};
use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::registry::Registry;
use aitts_engine::worker::{WorkerLaunch, WorkerSupervisor};
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::vocabulary::ModelState;
use aitts_store::queue::NewUtterance;
use aitts_store::{Store, SystemClock};
use support::{read_line, request};

const LIMIT: Duration = Duration::from_secs(20);

/// Every clip the sink played, with its PCM, in play order.
type Played = Arc<Mutex<Vec<(String, Vec<u8>)>>>;

fn drain(mut spool: Spool) -> Result<Vec<u8>, String> {
    let mut pcm = Vec::new();
    loop {
        spool.fill();
        let read = spool.read(4096);
        pcm.extend(read.pcm);
        if let Some(error) = read.error {
            return Err(error);
        }
        if read.complete || read.ended {
            return Ok(pcm);
        }
    }
}

/// Records each clip and announces it on `notify`.
struct RecordingSink {
    played: Played,
    notify: Sender<String>,
}
impl Sink for RecordingSink {
    fn play(&mut self, id: &str, spool: Spool) -> Result<(), String> {
        let pcm = drain(spool)?;
        self.played.lock().unwrap().push((id.to_owned(), pcm));
        let _unwatched = self.notify.send(id.to_owned());
        Ok(())
    }
}

/// Reports when it is reached, then waits for the gate before recording.
struct GatedSink {
    inner: RecordingSink,
    reached: Sender<String>,
    gate: Receiver<()>,
}
impl Sink for GatedSink {
    fn play(&mut self, id: &str, spool: Spool) -> Result<(), String> {
        let _unwatched = self.reached.send(id.to_owned());
        self.gate.recv().map_err(|_| "gate dropped".to_owned())?;
        self.inner.play(id, spool)
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

/// Lets the first `free` calls through, then reports each later call and
/// waits for the gate.
struct GatedEngine {
    inner: WorkerSupervisor,
    free: usize,
    reached: Sender<()>,
    gate: Receiver<()>,
}
impl Engine for GatedEngine {
    fn name(&self) -> &str {
        self.inner.name()
    }
    fn stream(
        &mut self,
        request: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        if self.free > 0 {
            self.free -= 1;
        } else {
            let _unwatched = self.reached.send(());
            self.gate
                .recv()
                .map_err(|_| EngineError::Refused("gate dropped"))?;
        }
        self.inner.stream(request, sink)
    }
    fn recover(&mut self) -> Result<(), EngineError> {
        self.inner.recover()
    }
}

struct Gate {
    open: Sender<()>,
    reached: Receiver<()>,
}

fn gated_engine(root: &Path, free: usize) -> (Box<dyn Engine>, Gate) {
    let (open, gate) = channel();
    let (reached, engine_reached) = channel();
    (
        Box::new(GatedEngine {
            inner: worker(root),
            free,
            reached,
            gate,
        }),
        Gate {
            open,
            reached: engine_reached,
        },
    )
}

struct Daemon {
    running: Option<aitts_daemon::Running>,
    socket: PathBuf,
    database: PathBuf,
    spools: PathBuf,
    played: Played,
    notified: Receiver<String>,
    idle: Receiver<()>,
    _dir: tempfile::TempDir,
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

fn synthesis(
    engine: Box<dyn Engine>,
    sink: Box<dyn Sink>,
    spools: &Path,
) -> (Synthesis, Receiver<()>) {
    let mut engines = Registry::default();
    assert!(engines.register(engine).is_ok());
    let (on_idle, idle) = channel();
    let synthesis = Synthesis {
        engines,
        spool_dir: spools.to_path_buf(),
        capacity_frames: 1024,
        sink,
        retry_after: Duration::from_millis(5),
        on_idle: Some(on_idle),
    };
    (synthesis, idle)
}

impl Daemon {
    fn start(engine: Box<dyn Engine>) -> Self {
        Self::start_with_sink(engine, |inner| Box::new(inner))
    }

    fn start_with_sink(
        engine: Box<dyn Engine>,
        sink: impl FnOnce(RecordingSink) -> Box<dyn Sink>,
    ) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let spools = dir.path().join("spools");
        fs::create_dir(&spools).unwrap();
        let config = config(dir.path());
        let played = Played::default();
        let (notify, notified) = channel();
        let recording = RecordingSink {
            played: Arc::clone(&played),
            notify,
        };
        let (synthesis, idle) = synthesis(engine, sink(recording), &spools);
        let (socket, database) = (config.socket.clone(), config.database.clone());
        let running = aitts_daemon::start_with(config, synthesis).unwrap();
        Self {
            running: Some(running),
            socket,
            database,
            spools,
            played,
            notified,
            idle,
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

    fn resume(&self) {
        assert!(matches!(
            self.ask(Operation::Resume, r#"{"op":"resume"}"#),
            Reply::Resume(_)
        ));
    }

    /// The stored state, read without sending the daemon a request.
    fn stored(&self, id: &str) -> aitts_store::State {
        let store = Store::open(&self.database, SystemClock).unwrap();
        store.queue().get(id).unwrap().unwrap().state
    }

    /// Wait, with a deadline and without waking the driver, until `id` is `wanted`.
    fn wait_stored(&self, id: &str, wanted: aitts_store::State) {
        let deadline = Instant::now() + LIMIT;
        loop {
            let state = self.stored(id);
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

    /// Run SQL on the daemon's database through a separate connection.
    fn sql(&self, statements: &str) {
        rusqlite::Connection::open(&self.database)
            .unwrap()
            .execute_batch(statements)
            .unwrap();
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        if let Some(running) = self.running.take() {
            let _outcome = running.stop(Duration::from_secs(5));
        }
    }
}

fn stream(text: &str) -> Vec<u8> {
    text.repeat(2).into_bytes()
}

#[test]
fn a_submitted_clip_is_played_after_only_the_submit_and_resume_wakes() {
    let root = runtime("golden");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    daemon.resume();
    let id = daemon.submit("Hello there.");
    // The sink's own notification: no further request can wake the driver.
    assert_eq!(daemon.notified.recv_timeout(LIMIT).unwrap(), id);
    assert_eq!(daemon.played(), [(id.clone(), stream("Hello there."))]);
    daemon.wait_stored(&id, aitts_store::State::Played);
}

#[test]
fn a_held_queue_plans_without_playing_until_resume() {
    let root = runtime("golden");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    // A started daemon is held, as after any restart.
    let id = daemon.submit("Wait for me.");
    daemon.wait_stored(&id, aitts_store::State::Ready);
    // Checkpoint: one more request wakes the driver, and its idle signal proves
    // a planning turn ran while the clip was Ready and the queue held.
    while daemon.idle.try_recv().is_ok() {}
    assert!(matches!(
        daemon.ask(Operation::Status, r#"{"op":"status"}"#),
        Reply::Status(_)
    ));
    daemon.idle.recv_timeout(LIMIT).unwrap();
    assert!(daemon.played().is_empty(), "a held queue played audio");
    daemon.resume();
    assert_eq!(daemon.notified.recv_timeout(LIMIT).unwrap(), id);
}

#[test]
fn a_ready_clip_plays_while_later_synthesis_is_still_running() {
    let root = runtime("golden");
    let (engine, gate) = gated_engine(root.path(), 1);
    let daemon = Daemon::start(engine);
    daemon.resume();
    let first = daemon.submit("First clip.");
    let second = daemon.submit("Second clip.");
    // The second synthesis is held in the engine; the first must still play.
    gate.reached.recv_timeout(LIMIT).unwrap();
    assert_eq!(
        daemon.notified.recv_timeout(LIMIT).unwrap(),
        first,
        "a ready clip waited for synthesis"
    );
    gate.open.send(()).unwrap();
    assert_eq!(daemon.notified.recv_timeout(LIMIT).unwrap(), second);
}

#[test]
fn a_clip_cancelled_during_synthesis_is_not_played_and_leaves_no_audio() {
    let root = runtime("golden");
    let (engine, gate) = gated_engine(root.path(), 0);
    let daemon = Daemon::start(engine);
    daemon.resume();
    let id = daemon.submit("Never mind.");
    gate.reached.recv_timeout(LIMIT).unwrap();
    assert!(matches!(
        daemon.ask(
            Operation::Cancel,
            &format!(r#"{{"op":"cancel","id":"{id}"}}"#)
        ),
        Reply::Cancel(_)
    ));
    gate.open.send(()).unwrap();
    let spool = daemon.spools.join(format!("{id}.wav"));
    let deadline = Instant::now() + LIMIT;
    while spool.exists() {
        assert!(
            Instant::now() < deadline,
            "the cancelled clip's audio was not removed"
        );
        std::thread::yield_now();
    }
    assert_eq!(daemon.stored(&id), aitts_store::State::Cancelled);
    assert!(daemon.played().is_empty(), "a cancelled clip was played");
}

#[test]
fn a_ready_clip_cancelled_while_held_releases_its_audio() {
    let root = runtime("golden");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    let id = daemon.submit("Not wanted.");
    daemon.wait_stored(&id, aitts_store::State::Ready);
    assert!(matches!(
        daemon.ask(
            Operation::Cancel,
            &format!(r#"{{"op":"cancel","id":"{id}"}}"#)
        ),
        Reply::Cancel(_)
    ));
    let spool = daemon.spools.join(format!("{id}.wav"));
    let deadline = Instant::now() + LIMIT;
    while spool.exists() {
        assert!(
            Instant::now() < deadline,
            "the cancelled ready clip's audio was kept"
        );
        std::thread::yield_now();
    }
}

#[test]
fn a_failed_synthesis_does_not_stop_later_clips() {
    let root = runtime("random 5 exit");
    let daemon = Daemon::start(Box::new(worker(root.path())));
    daemon.resume();
    let failed = daemon.submit("This fails.");
    daemon.wait_stored(&failed, aitts_store::State::Failed);
    fs::write(root.path().join("mode"), "golden").unwrap();
    let next = daemon.submit("This plays.");
    assert_eq!(daemon.notified.recv_timeout(LIMIT).unwrap(), next);
    assert_eq!(daemon.played(), [(next, stream("This plays."))]);
}

/// Make the ledger refuse to record `state`, through a trigger on the store.
fn refuse(daemon: &Daemon, state: &str) {
    daemon.sql(&format!(
        "CREATE TRIGGER refuse BEFORE UPDATE OF state ON utterances WHEN NEW.state = '{state}'
         BEGIN SELECT RAISE(ABORT, 'injected ledger failure'); END;"
    ));
}

#[test]
fn an_unrecorded_ready_report_is_retried_without_a_client_request() {
    let root = runtime("golden");
    let (engine, gate) = gated_engine(root.path(), 0);
    let daemon = Daemon::start(engine);
    daemon.resume();
    let id = daemon.submit("Retry me.");
    gate.reached.recv_timeout(LIMIT).unwrap();
    refuse(&daemon, "Ready");
    gate.open.send(()).unwrap();
    // Forced: the refused report has been made once the driver waits; a second
    // wait proves any wake left from earlier requests is used up.
    daemon.idle.recv_timeout(LIMIT).unwrap();
    daemon.idle.recv_timeout(LIMIT).unwrap();
    assert_eq!(daemon.stored(&id), aitts_store::State::Synthesizing);
    daemon.sql("DROP TRIGGER refuse;");
    // No request from here on: only the driver's own retry can finish the clip.
    assert_eq!(daemon.notified.recv_timeout(LIMIT).unwrap(), id);
}

#[test]
fn an_unrecorded_playback_report_is_retried_until_the_clip_is_played() {
    let root = runtime("golden");
    let (sink_reached, reached) = channel();
    let (open, gate) = channel();
    let daemon = Daemon::start_with_sink(Box::new(worker(root.path())), |inner| {
        Box::new(GatedSink {
            inner,
            reached: sink_reached,
            gate,
        })
    });
    daemon.resume();
    let id = daemon.submit("Finish me.");
    assert_eq!(reached.recv_timeout(LIMIT).unwrap(), id);
    refuse(&daemon, "Played");
    open.send(()).unwrap();
    assert_eq!(daemon.notified.recv_timeout(LIMIT).unwrap(), id);
    daemon.sql("DROP TRIGGER refuse;");
    daemon.wait_stored(&id, aitts_store::State::Played);
}

#[test]
fn a_clip_that_finishes_during_a_pause_is_played_and_not_replayed() {
    let root = runtime("golden");
    let (sink_reached, reached) = channel();
    let (open, gate) = channel();
    let daemon = Daemon::start_with_sink(Box::new(worker(root.path())), |inner| {
        Box::new(GatedSink {
            inner,
            reached: sink_reached,
            gate,
        })
    });
    daemon.resume();
    let id = daemon.submit("Pause in the middle.");
    assert_eq!(reached.recv_timeout(LIMIT).unwrap(), id);
    assert!(
        matches!(daemon.ask(Operation::Pause, r#"{"op":"pause"}"#), Reply::Pause(ref t) if t.held)
    );
    open.send(()).unwrap();
    daemon.wait_stored(&id, aitts_store::State::Played);
    daemon.resume();
    // Checkpoint: after the resume the driver plans again and goes idle.
    while daemon.idle.try_recv().is_ok() {}
    assert!(matches!(
        daemon.ask(Operation::Status, r#"{"op":"status"}"#),
        Reply::Status(_)
    ));
    daemon.idle.recv_timeout(LIMIT).unwrap();
    assert_eq!(daemon.played().len(), 1, "a finished clip was played again");
}

#[test]
fn stop_takes_no_new_clip_after_the_one_in_the_sink() {
    let root = runtime("golden");
    let (engine, gate) = gated_engine(root.path(), 1);
    let (sink_reached, reached) = channel();
    let (open, sink_gate) = channel();
    let mut daemon = Daemon::start_with_sink(engine, |inner| {
        Box::new(GatedSink {
            inner,
            reached: sink_reached,
            gate: sink_gate,
        })
    });
    daemon.resume();
    let first = daemon.submit("In the sink.");
    assert_eq!(reached.recv_timeout(LIMIT).unwrap(), first);
    // Queued while the driver is in the sink, so it is not yet synthesized.
    let _second = daemon.submit("Never started.");
    // An open connection ends when stop has begun (its stop signal precedes it).
    let watcher = UnixStream::connect(&daemon.socket).unwrap();
    let running = daemon.running.take().unwrap();
    let stopping = std::thread::spawn(move || running.stop(LIMIT));
    assert!(
        read_line(&watcher).is_empty(),
        "stop did not close connections"
    );
    open.send(()).unwrap();
    let _outcome = stopping.join().unwrap();
    assert!(
        gate.reached.try_recv().is_err(),
        "the driver synthesized a clip after stop began"
    );
    assert!(
        reached.try_recv().is_err(),
        "the driver played a clip after stop began"
    );
    assert_eq!(daemon.played().len(), 1);
}

#[test]
fn start_with_refuses_a_missing_spool_directory() {
    let dir = tempfile::tempdir().unwrap();
    let root = runtime("golden");
    let (synthesis, _idle) = synthesis(
        Box::new(worker(root.path())),
        Box::new(DiscardingSink),
        &dir.path().join("missing"),
    );
    let started = aitts_daemon::start_with(config(dir.path()), synthesis);
    assert!(matches!(started, Err(StartError::Io(_))), "got {started:?}");
}

#[test]
fn a_failed_start_takes_no_recovered_work() {
    let dir = tempfile::tempdir().unwrap();
    let config = config(dir.path());
    // Queued work that recovery restores, and a socket path the bind refuses.
    let store = Store::open(&config.database, SystemClock).unwrap();
    let mut new = NewUtterance::new(
        "utt_a".to_owned(),
        "text".to_owned(),
        "bm_daniel".to_owned(),
        1.0,
    );
    new.engine = Some("fake".to_owned());
    store.queue().submit(&new).unwrap();
    store.close().unwrap();
    fs::write(&config.socket, "not a socket").unwrap();
    let root = runtime("golden");
    let (engine, gate) = gated_engine(root.path(), 0);
    let spools = dir.path().join("spools");
    fs::create_dir(&spools).unwrap();
    let (synthesis, _idle) = synthesis(engine, Box::new(DiscardingSink), &spools);
    drop(gate.open);
    let started = aitts_daemon::start_with(config, synthesis);
    assert!(
        matches!(started, Err(StartError::SocketOccupied)),
        "got {started:?}"
    );
    assert!(
        gate.reached.try_recv().is_err(),
        "the driver took work before the socket was ready"
    );
}

/// Storage whose reads fail after `readable` bytes, as a failing disk would.
#[derive(Debug)]
struct FailingReads {
    bytes: Vec<u8>,
    readable: u64,
}
impl SpoolStorage for FailingReads {
    fn write_all_at(&mut self, buf: &[u8], offset: u64) -> std::io::Result<()> {
        let end = usize::try_from(offset).unwrap() + buf.len();
        if self.bytes.len() < end {
            self.bytes.resize(end, 0);
        }
        self.bytes[usize::try_from(offset).unwrap()..end].copy_from_slice(buf);
        Ok(())
    }
    fn read_exact_at(&self, buf: &mut [u8], offset: u64) -> std::io::Result<()> {
        if offset + u64::try_from(buf.len()).unwrap() > self.readable {
            return Err(std::io::Error::other("injected read failure"));
        }
        let start = usize::try_from(offset).unwrap();
        buf.copy_from_slice(&self.bytes[start..start + buf.len()]);
        Ok(())
    }
}

#[test]
fn the_discarding_sink_reports_a_read_failure_after_some_frames() {
    // A one-frame ring: the first frame is buffered; the second must be re-read
    // from storage, which fails.
    let storage = FailingReads {
        bytes: Vec::new(),
        readable: 44,
    };
    let mut spool = Spool::with_storage(Box::new(storage), 1).unwrap();
    spool.append(&[1, 0, 2, 0]).unwrap();
    spool.seal().unwrap();
    spool.finish(None);
    assert!(
        DiscardingSink.play("a", spool).is_err(),
        "a mid-stream read failure played as complete"
    );
}

#[test]
fn the_discarding_sink_reports_a_spool_that_ended_with_an_error() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&dir.path().join("a.wav"), 1).unwrap();
    spool.append(&[1, 0]).unwrap();
    spool.finish(Some("worker exited".to_owned()));
    assert!(
        DiscardingSink.play("a", spool).is_err(),
        "a failed spool played as complete"
    );
}
