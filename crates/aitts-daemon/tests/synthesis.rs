// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (a real worker subprocess, owned temporary files, one helper thread).
//! The synthesis scheduler: engine registry to spool to conductor.
//! Oracles: the fake worker of `aitts-engine` speaks worker protocol 2 in the real
//! argument shape, and its known stream is each text byte twice; the conductor
//! contract (cancelled audio is discarded, failure marks the clip failed, a ledger
//! failure changes nothing); the spool contract (a sealed WAV reopens through
//! `Spool::open_cached`; a finished spool returns only written frames and its error).
//! Interleavings are forced: the conductor owner is stepped on the test thread,
//! and a gate holds the engine until the test opens it. Never raced. Gates and
//! inboxes live inside the scope closure, so a failed assertion releases the
//! worker thread instead of hanging the join.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "test code fails loudly"
)]

use std::cell::Cell;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::rc::Rc;
use std::sync::mpsc::{Receiver, Sender, channel as gate_channel};
use std::thread;
use std::time::Duration;

use aitts_artifacts::spool::Spool;
use aitts_daemon::conductor::durable::{Change, Durable, Ledger, LedgerError};
use aitts_daemon::conductor::mailbox::{Mailbox, Reply, Request, Served, channel};
use aitts_daemon::conductor::{Clip, Command, Transfer};
use aitts_daemon::synthesis::{Finished, Job, SpoolTarget, SynthesisError, retry, synthesize};
use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;
use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::registry::Registry;
use aitts_engine::worker::{WorkerLaunch, WorkerSupervisor};

const TEXT: &str = "hello world";

/// A ledger that refuses every record while `refusing` is set.
#[derive(Clone, Default)]
struct Switch {
    refusing: Rc<Cell<bool>>,
}
impl Ledger for Switch {
    fn record(&mut self, _changes: &[Change]) -> Result<(), LedgerError> {
        if self.refusing.get() {
            Err(LedgerError::Unavailable)
        } else {
            Ok(())
        }
    }
    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        Ok(Vec::new())
    }
}

/// Run synthesis on a scoped thread with its own sender, so the owner's wait ends
/// (as `Served::Stopped`) if synthesis returns without reporting.
fn start<'scope>(
    scope: &'scope thread::Scope<'scope, '_>,
    job: Job,
    engines: &'scope mut Registry,
    target: SpoolTarget,
    mailbox: Mailbox,
) -> thread::ScopedJoinHandle<'scope, Finished> {
    scope.spawn(move || synthesize(&job, engines, &target, &mailbox))
}

/// A runtime root whose `venv/bin/python` runs a copy of `fixture`. The path is
/// never written into shell source, so any characters in it are safe.
fn runtime_from(fixture: &Path, mode: &str) -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    let bin = root.path().join("venv/bin");
    fs::create_dir_all(&bin).unwrap();
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

fn fixture() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../aitts-engine/tests/fixtures/fake_worker.py")
}

fn runtime(mode: &str) -> tempfile::TempDir {
    runtime_from(&fixture(), mode)
}

fn worker(root: &Path) -> WorkerSupervisor {
    WorkerSupervisor::new(
        "kokoro",
        WorkerLaunch::python_runtime("kokoro", root),
        Duration::from_secs(10),
    )
}

/// Holds the engine until the test sends on the gate; a dropped gate releases it.
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
        // Tell the test the engine is reached (the spool exists), then wait.
        let _unwatched = self.reached.send(());
        self.gate
            .recv()
            .map_err(|_| EngineError::Refused("gate dropped"))?;
        self.inner.stream(request, sink)
    }
}

/// Sends half a sample (a spool write failure), then fails itself.
struct HalfSampleThenFail;
impl Engine for HalfSampleThenFail {
    fn name(&self) -> &'static str {
        "kokoro"
    }
    fn stream(
        &mut self,
        _: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        sink(&[1]);
        Err(EngineError::ModelFailed)
    }
}

fn registry(engine: Box<dyn Engine>) -> Registry {
    let mut registry = Registry::default();
    assert!(registry.register(engine).is_ok());
    registry
}

fn gated(root: &Path) -> (Registry, Sender<()>, Receiver<()>) {
    let (open, gate) = gate_channel();
    let (reached, engine_reached) = gate_channel();
    let engine = Gated {
        inner: worker(root),
        gate,
        reached,
    };
    (registry(Box::new(engine)), open, engine_reached)
}

fn job(id: &str, engine: &str) -> Job {
    Job {
        id: id.to_owned(),
        text: TEXT.to_owned(),
        voice: "default".to_owned(),
        speed: 1.0,
        engine: engine.to_owned(),
    }
}

fn target(dir: &Path, id: &str) -> SpoolTarget {
    SpoolTarget {
        path: dir.join(format!("{id}.wav")),
        capacity_frames: 1024,
    }
}

/// An open owner with each clip submitted and the first handed to synthesis.
fn owner_with(ledger: Switch, ids: &[(&str, Priority)]) -> Durable<Switch> {
    let mut owner = Durable::recover(ledger).unwrap();
    owner.apply(Command::Resume).unwrap();
    for (id, priority) in ids {
        let submit = Command::Submit {
            id: (*id).to_owned(),
            priority: *priority,
            playback: Playback::Play,
        };
        owner.apply(submit).unwrap();
    }
    owner.next_synthesis().unwrap();
    owner
}

fn owner(ids: &[(&str, Priority)]) -> Durable<Switch> {
    owner_with(Switch::default(), ids)
}

fn state(owner: &Durable<Switch>, id: &str) -> State {
    owner
        .conductor()
        .clips()
        .into_iter()
        .find(|clip| clip.id == id)
        .unwrap()
        .state
}

fn known_stream() -> Vec<u8> {
    TEXT.repeat(2).into_bytes()
}

fn ready(id: &str) -> Served {
    Served::Answered(Request::Apply(Command::AudioReady(id.to_owned())))
}

fn failure(id: &str) -> Served {
    Served::Answered(Request::Apply(Command::SynthesisFailed(id.to_owned())))
}

/// Synthesize `id` on a helper thread and step the owner once for its report.
fn run_one(
    owner: &mut Durable<Switch>,
    engines: &mut Registry,
    dir: &Path,
    id: &str,
) -> (Served, Finished) {
    let (mailbox, inbox) = channel(1);
    thread::scope(|scope| {
        let done = start(scope, job(id, "kokoro"), engines, target(dir, id), mailbox);
        let served = inbox.step(owner);
        drop(inbox);
        (served, done.join().unwrap())
    })
}

#[test]
fn synthesis_seals_the_known_stream_and_marks_the_clip_ready() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    let (served, finished) = run_one(&mut owner, &mut engines, dir.path(), "a");
    assert_eq!(served, ready("a"));
    assert!(
        matches!(finished, Finished::Ready(_)),
        "expected ready, got {finished:?}"
    );
    // The sealed WAV reopens as cached audio; an unsealed header would be refused.
    let mut cached = Spool::open_cached(&dir.path().join("a.wav"), 1024).unwrap();
    cached.fill();
    assert_eq!(cached.read(1024).pcm, known_stream());
    assert_eq!(state(&owner, "a"), State::Ready);
}

#[test]
fn audio_for_a_clip_cancelled_during_synthesis_is_discarded_and_its_file_removed() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let (mut engines, open, _engine_reached) = gated(root.path());
    let (mailbox, inbox) = channel(2);
    let finished = thread::scope(|scope| {
        // Owned by the closure: unwinding drops them and releases the worker.
        let (open, inbox, mailbox) = (open, inbox, mailbox);
        let done = start(
            scope,
            job("a", "kokoro"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox.clone(),
        );
        // Forced order: the cancel is answered while the engine is held.
        drop(
            mailbox
                .try_request(Request::Apply(Command::Cancel("a".to_owned())))
                .unwrap(),
        );
        drop(mailbox);
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::Cancel("a".to_owned())))
        );
        open.send(()).unwrap();
        assert_eq!(inbox.step(&mut owner), ready("a"));
        assert_eq!(state(&owner, "a"), State::Cancelled);
        let finished = done.join().unwrap();
        assert!(
            !dir.path().join("a.wav").exists(),
            "discarded audio left its spool file"
        );
        finished
    });
    assert!(
        matches!(finished, Finished::Discarded),
        "expected discarded, got {finished:?}"
    );
}

#[test]
fn a_worker_exit_mid_stream_fails_the_clip_and_keeps_a_partial_safe_spool() {
    // Seed 5 of the fake worker's schedule exits after some frames are sent.
    let root = runtime("random 5 exit");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    let (served, finished) = run_one(&mut owner, &mut engines, dir.path(), "a");
    assert_eq!(served, failure("a"));
    let Finished::Failed {
        spool: Some(mut spool),
        error: SynthesisError::Engine(_),
    } = finished
    else {
        panic!("expected an engine failure with a spool, got {finished:?}")
    };
    let read = spool.read(1024);
    let known = known_stream();
    assert!(
        !read.pcm.is_empty() && read.pcm.len() < known.len(),
        "expected a partial stream, got {} bytes",
        read.pcm.len()
    );
    assert_eq!(
        read.pcm,
        known[..read.pcm.len()],
        "partial audio is not a prefix of the known stream"
    );
    assert!(
        read.error.is_some() && read.ended,
        "the partial spool does not report its failure: {read:?}"
    );
    assert_eq!(state(&owner, "a"), State::Failed);
}

#[test]
fn a_failed_worker_is_restored_before_the_next_clip() {
    let root = runtime("random 5 exit");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal), ("b", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    assert_eq!(
        run_one(&mut owner, &mut engines, dir.path(), "a").0,
        failure("a")
    );
    fs::write(root.path().join("mode"), "golden").unwrap();
    assert_eq!(owner.next_synthesis().unwrap().as_deref(), Some("b"));
    let (served, finished) = run_one(&mut owner, &mut engines, dir.path(), "b");
    assert_eq!(
        served,
        ready("b"),
        "the failed worker was not restored; got {finished:?}"
    );
}

#[test]
fn preempting_audio_that_finishes_after_a_plan_step_takes_the_device_on_the_next_plan() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("base", Priority::Normal)]);
    owner.apply(Command::AudioReady("base".to_owned())).unwrap();
    assert_eq!(
        owner.plan_playback().unwrap(),
        Some(Transfer::Start("base".to_owned()))
    );
    let submit = Command::Submit {
        id: "alert".to_owned(),
        priority: Priority::Preempt,
        playback: Playback::Play,
    };
    owner.apply(submit).unwrap();
    assert_eq!(owner.next_synthesis().unwrap().as_deref(), Some("alert"));
    let (mut engines, open, _engine_reached) = gated(root.path());
    let (mailbox, inbox) = channel(2);
    thread::scope(|scope| {
        // Owned by the closure: unwinding drops them and releases the worker.
        let (open, inbox, mailbox) = (open, inbox, mailbox);
        let done = start(
            scope,
            job("alert", "kokoro"),
            &mut engines,
            target(dir.path(), "alert"),
            mailbox.clone(),
        );
        // Forced order: a plan while the alert is still synthesizing changes nothing.
        let early = mailbox.try_request(Request::PlanPlayback).unwrap();
        drop(mailbox);
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::PlanPlayback)
        );
        assert!(
            matches!(early.wait().unwrap(), Reply::Planned(Ok(None))),
            "a plan moved the device early"
        );
        open.send(()).unwrap();
        assert_eq!(inbox.step(&mut owner), ready("alert"));
        assert!(matches!(done.join().unwrap(), Finished::Ready(_)));
    });
    let preempt = Transfer::Preempt {
        suspended: Some("base".to_owned()),
        started: "alert".to_owned(),
    };
    assert_eq!(owner.plan_playback().unwrap(), Some(preempt));
}

#[test]
fn an_unknown_engine_fails_the_clip() {
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = Registry::default();
    let (mailbox, inbox) = channel(1);
    let finished = thread::scope(|scope| {
        let done = start(
            scope,
            job("a", "missing"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox,
        );
        assert_eq!(inbox.step(&mut owner), failure("a"));
        drop(inbox);
        done.join().unwrap()
    });
    assert!(
        matches!(
            finished,
            Finished::Failed {
                spool: None,
                error: SynthesisError::NoEngine(_)
            }
        ),
        "got {finished:?}"
    );
    assert_eq!(state(&owner, "a"), State::Failed);
}

#[test]
fn the_first_write_failure_is_reported_over_a_later_engine_error() {
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(HalfSampleThenFail));
    let (served, finished) = run_one(&mut owner, &mut engines, dir.path(), "a");
    assert_eq!(served, failure("a"));
    assert!(
        matches!(
            finished,
            Finished::Failed {
                error: SynthesisError::Write(_),
                ..
            }
        ),
        "got {finished:?}"
    );
}

#[test]
fn a_ledger_refusing_audio_ready_keeps_the_sealed_audio_for_retry() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let ledger = Switch::default();
    let mut owner = owner_with(ledger.clone(), &[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    ledger.refusing.set(true);
    let (served, finished) = run_one(&mut owner, &mut engines, dir.path(), "a");
    assert_eq!(served, ready("a"));
    let Finished::Unreported(unreported) = finished else {
        panic!("expected unreported, got {finished:?}")
    };
    assert_eq!(unreported.report, Command::AudioReady("a".to_owned()));
    assert!(dir.path().join("a.wav").exists(), "owed audio was removed");
    assert_eq!(state(&owner, "a"), State::Synthesizing);
    // The retry sends the report again; it cannot reach the engine.
    ledger.refusing.set(false);
    let (mailbox, inbox) = channel(1);
    let finished = thread::scope(|scope| {
        let done = scope.spawn(move || retry(unreported, &mailbox));
        assert_eq!(inbox.step(&mut owner), ready("a"));
        drop(inbox);
        done.join().unwrap()
    });
    assert!(
        matches!(finished, Finished::Ready(_)),
        "retry did not record the audio: {finished:?}"
    );
    assert_eq!(state(&owner, "a"), State::Ready);
}

#[test]
fn a_ledger_refusing_synthesis_failed_returns_the_failure_unreported() {
    let dir = tempfile::tempdir().unwrap();
    let ledger = Switch::default();
    let mut owner = owner_with(ledger.clone(), &[("a", Priority::Normal)]);
    let mut engines = Registry::default();
    ledger.refusing.set(true);
    let (mailbox, inbox) = channel(1);
    let finished = thread::scope(|scope| {
        let done = start(
            scope,
            job("a", "missing"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox,
        );
        assert_eq!(inbox.step(&mut owner), failure("a"));
        drop(inbox);
        done.join().unwrap()
    });
    let Finished::Unreported(unreported) = finished else {
        panic!("expected unreported, got {finished:?}")
    };
    assert_eq!(unreported.report, Command::SynthesisFailed("a".to_owned()));
    assert!(
        matches!(unreported.error, Some(SynthesisError::NoEngine(_))),
        "the failure was lost"
    );
    assert_eq!(state(&owner, "a"), State::Synthesizing);
}

#[test]
fn a_shutdown_before_the_ready_report_removes_the_unreported_audio() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    let (mailbox, inbox) = channel(2);
    // Forced order: the shutdown is queued before synthesis can report.
    drop(mailbox.try_request(Request::Shutdown).unwrap());
    assert_eq!(inbox.step(&mut owner), Served::Stopped);
    drop(inbox);
    let finished = synthesize(
        &job("a", "kokoro"),
        &mut engines,
        &target(dir.path(), "a"),
        &mailbox,
    );
    assert!(matches!(finished, Finished::Closed), "got {finished:?}");
    assert!(
        !dir.path().join("a.wav").exists(),
        "unreported audio was left behind"
    );
}

#[test]
fn a_shutdown_before_the_failure_report_removes_the_partial_audio() {
    let root = runtime("random 5 exit");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    let (mailbox, inbox) = channel(2);
    drop(mailbox.try_request(Request::Shutdown).unwrap());
    assert_eq!(inbox.step(&mut owner), Served::Stopped);
    drop(inbox);
    let finished = synthesize(
        &job("a", "kokoro"),
        &mut engines,
        &target(dir.path(), "a"),
        &mailbox,
    );
    assert!(matches!(finished, Finished::Closed), "got {finished:?}");
    assert!(
        !dir.path().join("a.wav").exists(),
        "unreported partial audio was left behind"
    );
}

#[test]
fn an_unremovable_discarded_file_is_reported_as_cleanup_failed() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let spools = dir.path().join("spools");
    fs::create_dir(&spools).unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let (mut engines, open, engine_reached) = gated(root.path());
    let (mailbox, inbox) = channel(2);
    let finished = thread::scope(|scope| {
        // Owned by the closure: unwinding drops them and releases the worker.
        let (open, inbox, mailbox) = (open, inbox, mailbox);
        let done = start(
            scope,
            job("a", "kokoro"),
            &mut engines,
            target(&spools, "a"),
            mailbox.clone(),
        );
        drop(
            mailbox
                .try_request(Request::Apply(Command::Cancel("a".to_owned())))
                .unwrap(),
        );
        drop(mailbox);
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::Cancel("a".to_owned())))
        );
        // Forced: wait until the engine is reached (the spool exists), then deny removal.
        engine_reached.recv().unwrap();
        fs::set_permissions(&spools, fs::Permissions::from_mode(0o500)).unwrap();
        open.send(()).unwrap();
        assert_eq!(inbox.step(&mut owner), ready("a"));
        drop(inbox);
        done.join().unwrap()
    });
    fs::set_permissions(&spools, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(
        matches!(finished, Finished::CleanupFailed { .. }),
        "got {finished:?}"
    );
    assert!(spools.join("a.wav").exists());
}

#[test]
fn a_fixture_path_with_an_apostrophe_starts_the_worker() {
    let quoted = tempfile::Builder::new().prefix("it's").tempdir().unwrap();
    let copy = quoted.path().join("fake_worker.py");
    fs::copy(fixture(), &copy).unwrap();
    let root = runtime_from(&copy, "golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner(&[("a", Priority::Normal)]);
    let mut engines = registry(Box::new(worker(root.path())));
    assert_eq!(
        run_one(&mut owner, &mut engines, dir.path(), "a").0,
        ready("a")
    );
}
