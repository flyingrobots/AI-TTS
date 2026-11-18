// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (a real worker subprocess, owned temporary files, one helper thread).
//! The synthesis scheduler: engine registry to spool to conductor.
//! Oracles: the fake worker of `aitts-engine` speaks worker protocol 2 in the real
//! argument shape, and its known stream is each text byte twice; the conductor
//! contract (cancelled audio is discarded, failure marks the clip failed); the
//! spool contract (a finished spool returns only written frames and its error).
//! Interleavings are forced: the conductor owner is stepped on the test thread,
//! and a gate holds the engine until the test opens it. Never raced.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "test code fails loudly"
)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::mpsc::{Receiver, Sender, channel as gate_channel};
use std::thread;
use std::time::Duration;

use aitts_daemon::conductor::durable::{Change, Durable, Ledger, LedgerError};
use aitts_daemon::conductor::mailbox::{Mailbox, Request, Served, channel};
use aitts_daemon::conductor::{Clip, Command, Transfer};
use aitts_daemon::synthesis::{Finished, Job, SpoolTarget, synthesize};
use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;
use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::registry::Registry;
use aitts_engine::worker::{WorkerLaunch, WorkerSupervisor};

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

const TEXT: &str = "hello world";

struct Accepting;
impl Ledger for Accepting {
    fn record(&mut self, _changes: &[Change]) -> Result<(), LedgerError> {
        Ok(())
    }
    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        Ok(Vec::new())
    }
}

/// A runtime root whose `venv/bin/python` runs the engine crate's fake worker.
fn runtime(mode: &str) -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    let bin = root.path().join("venv/bin");
    fs::create_dir_all(&bin).unwrap();
    let fake =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../aitts-engine/tests/fixtures/fake_worker.py");
    let python = bin.join("python");
    fs::write(
        &python,
        format!("#!/bin/sh\nexec python3 '{}' \"$@\"\n", fake.display()),
    )
    .unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(root.path().join("mode"), mode).unwrap();
    root
}

fn worker(root: &Path) -> WorkerSupervisor {
    WorkerSupervisor::new(
        "kokoro",
        WorkerLaunch::python_runtime("kokoro", root),
        Duration::from_secs(10),
    )
}

/// Holds the engine until the test sends on the gate.
struct Gated {
    inner: WorkerSupervisor,
    gate: Receiver<()>,
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
        self.gate.recv().unwrap();
        self.inner.stream(request, sink)
    }
}

fn registry(engine: Box<dyn Engine>) -> Registry {
    let mut registry = Registry::default();
    assert!(registry.register(engine).is_ok());
    registry
}

fn gated(root: &Path) -> (Registry, Sender<()>) {
    let (open, gate) = gate_channel();
    (
        registry(Box::new(Gated {
            inner: worker(root),
            gate,
        })),
        open,
    )
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

/// An owner with `id` submitted and handed to synthesis.
fn owner_synthesizing(ids: &[(&str, Priority)]) -> Durable<Accepting> {
    let mut owner = Durable::recover(Accepting).unwrap();
    owner.apply(Command::Resume).unwrap();
    for (id, priority) in ids {
        let submit = Command::Submit {
            id: (*id).to_owned(),
            priority: *priority,
            playback: Playback::Play,
        };
        owner.apply(submit).unwrap();
    }
    owner
}

fn state(owner: &Durable<Accepting>, id: &str) -> State {
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

#[test]
fn synthesis_seals_the_known_stream_and_marks_the_clip_ready() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner_synthesizing(&[("a", Priority::Normal)]);
    assert_eq!(owner.next_synthesis().unwrap().as_deref(), Some("a"));
    let (mailbox, inbox) = channel(1);
    let mut engines = registry(Box::new(worker(root.path())));
    let finished = thread::scope(|scope| {
        let done = start(
            scope,
            job("a", "kokoro"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox.clone(),
        );
        drop(mailbox);
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::AudioReady("a".to_owned())))
        );
        done.join().unwrap()
    });
    let Finished::Ready(mut spool) = finished else {
        panic!("expected ready, got {finished:?}")
    };
    assert_eq!(spool.read(1024).pcm, known_stream());
    assert_eq!(state(&owner, "a"), State::Ready);
}

#[test]
fn audio_for_a_clip_cancelled_during_synthesis_is_discarded_and_its_file_removed() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner_synthesizing(&[("a", Priority::Normal)]);
    assert_eq!(owner.next_synthesis().unwrap().as_deref(), Some("a"));
    let (mailbox, inbox) = channel(2);
    let (mut engines, open) = gated(root.path());
    let finished = thread::scope(|scope| {
        let done = start(
            scope,
            job("a", "kokoro"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox.clone(),
        );
        // Forced order: the cancel is answered while the engine is held.
        let cancel = mailbox
            .try_request(Request::Apply(Command::Cancel("a".to_owned())))
            .unwrap();
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::Cancel("a".to_owned())))
        );
        drop(cancel);
        drop(mailbox);
        open.send(()).unwrap();
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::AudioReady("a".to_owned())))
        );
        done.join().unwrap()
    });
    assert!(
        matches!(finished, Finished::Discarded),
        "expected discarded, got {finished:?}"
    );
    assert!(
        !dir.path().join("a.wav").exists(),
        "discarded audio left its spool file"
    );
    assert_eq!(state(&owner, "a"), State::Cancelled);
}

#[test]
fn a_worker_exit_mid_stream_fails_the_clip_and_keeps_a_partial_safe_spool() {
    // Seed 5 of the fake worker's schedule exits after some frames are sent.
    let root = runtime("random 5 exit");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner_synthesizing(&[("a", Priority::Normal)]);
    assert_eq!(owner.next_synthesis().unwrap().as_deref(), Some("a"));
    let (mailbox, inbox) = channel(1);
    let mut engines = registry(Box::new(worker(root.path())));
    let finished = thread::scope(|scope| {
        let done = start(
            scope,
            job("a", "kokoro"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox.clone(),
        );
        drop(mailbox);
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::SynthesisFailed("a".to_owned())))
        );
        done.join().unwrap()
    });
    let Finished::Failed {
        spool: Some(mut spool),
        ..
    } = finished
    else {
        panic!("expected failed with a spool, got {finished:?}")
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
fn preempting_audio_that_finishes_after_a_plan_step_takes_the_device_on_the_next_plan() {
    let root = runtime("golden");
    let dir = tempfile::tempdir().unwrap();
    let mut owner = owner_synthesizing(&[("base", Priority::Normal)]);
    owner.next_synthesis().unwrap();
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
    let (mailbox, inbox) = channel(2);
    let (mut engines, open) = gated(root.path());
    thread::scope(|scope| {
        let done = start(
            scope,
            job("alert", "kokoro"),
            &mut engines,
            target(dir.path(), "alert"),
            mailbox.clone(),
        );
        // Forced order: a plan while the alert is still synthesizing changes nothing.
        let early = mailbox.try_request(Request::PlanPlayback).unwrap();
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::PlanPlayback)
        );
        assert!(matches!(
            early.wait().unwrap(),
            aitts_daemon::conductor::mailbox::Reply::Planned(Ok(None))
        ));
        drop(mailbox);
        open.send(()).unwrap();
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::AudioReady("alert".to_owned())))
        );
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
    let mut owner = owner_synthesizing(&[("a", Priority::Normal)]);
    owner.next_synthesis().unwrap();
    let (mailbox, inbox) = channel(1);
    let mut engines = Registry::default();
    let finished = thread::scope(|scope| {
        let done = start(
            scope,
            job("a", "missing"),
            &mut engines,
            target(dir.path(), "a"),
            mailbox.clone(),
        );
        drop(mailbox);
        assert_eq!(
            inbox.step(&mut owner),
            Served::Answered(Request::Apply(Command::SynthesisFailed("a".to_owned())))
        );
        done.join().unwrap()
    });
    assert!(
        matches!(finished, Finished::Failed { spool: None, .. }),
        "got {finished:?}"
    );
    assert_eq!(state(&owner, "a"), State::Failed);
}
