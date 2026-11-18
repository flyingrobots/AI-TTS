// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the loop that drives synthesis ahead of playback.
//!
//! One driver thread alternates a playback turn (play the transfer the
//! conductor plans, through a [`Sink`]) with a synthesis turn (run
//! [`crate::synthesis::synthesize`] for the next clip), so a ready clip never
//! waits for a synthesis backlog and a held queue still synthesizes. It reads
//! clips through the conductor, so it opens no store of its own.
//!
//! Reports the ledger did not record are kept and resent before new work, with
//! a doubling wait from [`Synthesis::retry_after`] up to [`MAX_RETRY_WAIT`]; no
//! client request is needed. Sealed spools are kept until their clip plays;
//! the spool of a clip that is no longer owed is closed and its file removed.
//! The thread takes no work until the daemon is serving, and takes no new clip
//! once the daemon begins to stop. When idle it sleeps on the API's wake signal.

use std::collections::{BTreeMap, VecDeque};
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender, SyncSender, sync_channel};
use std::thread::JoinHandle;
use std::time::Duration;

use aitts_artifacts::spool::Spool;
use aitts_domain::utterance::State;
use aitts_engine::registry::Registry;

use crate::conductor::durable::DurableError;
use crate::conductor::mailbox::{Mailbox, Reply, Request};
use crate::conductor::{Command, Transfer};
use crate::synthesis::{Finished, Job, SpoolTarget, Unreported, retry, synthesize};

/// An audio output. It owns the device while `play` runs.
pub trait Sink: Send {
    /// Play `spool` for clip `id` to its end.
    ///
    /// # Errors
    /// Returns a description of the device failure; the clip is then failed.
    fn play(&mut self, id: &str, spool: Spool) -> Result<(), String>;
}

/// A sink that reads every frame and discards it, for daemons without a device.
#[derive(Debug, Default)]
pub struct DiscardingSink;

impl Sink for DiscardingSink {
    fn play(&mut self, _id: &str, mut spool: Spool) -> Result<(), String> {
        loop {
            spool.fill();
            let read = spool.read(READ_FRAMES);
            if let Some(error) = read.error {
                return Err(error);
            }
            if read.complete || read.ended {
                return Ok(());
            }
            if read.pcm.is_empty() {
                // A sealed spool always fills; an empty read here cannot progress.
                return Err("spool returned no frames before its end".to_owned());
            }
        }
    }
}

/// Frames read per sink step.
const READ_FRAMES: usize = 4096;

/// What the driver needs to synthesize and play.
pub struct Synthesis {
    /// The engines clips may name.
    pub engines: Registry,
    /// The directory that holds each clip's spool, `<id>.wav`.
    pub spool_dir: PathBuf,
    /// Frames each spool's read ring holds.
    pub capacity_frames: usize,
    /// The audio output.
    pub sink: Box<dyn Sink>,
    /// The first wait before resending a report the ledger did not record;
    /// later waits double, up to [`MAX_RETRY_WAIT`].
    pub retry_after: Duration,
    /// Signalled each time the driver finds no work and waits: an observation
    /// point for diagnostics and tests. A disconnected receiver is ignored.
    pub on_idle: Option<Sender<()>>,
}

/// The longest wait between report retries.
pub const MAX_RETRY_WAIT: Duration = Duration::from_secs(2);

impl std::fmt::Debug for Synthesis {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Synthesis")
            .field("spool_dir", &self.spool_dir)
            .finish_non_exhaustive()
    }
}

/// The running driver, as the daemon's start and stop see it.
pub(crate) struct DriverHandle {
    pub(crate) thread: JoinHandle<()>,
    go: SyncSender<()>,
    stopping: Arc<AtomicBool>,
}

impl DriverHandle {
    /// Let the driver take work; the daemon is serving.
    pub(crate) fn go(&self) {
        // A driver that already ended has nothing to start.
        let _ended = self.go.try_send(());
    }

    /// Release a driver that never started, and wait for it to end.
    pub(crate) fn abandon(self) {
        drop(self.go);
        let _ = self.thread.join();
    }

    /// Take no new clip from now on; an operation in progress settles.
    pub(crate) fn begin_stop(&self) {
        self.stopping.store(true, Ordering::SeqCst);
    }
}

/// Start the driver thread. It waits for [`DriverHandle::go`] before any work,
/// and ends without work if the handle is dropped first.
///
/// # Errors
/// Returns an error when the spool directory is not a directory, or the thread
/// cannot start.
pub(crate) fn spawn(
    synthesis: Synthesis,
    mailbox: Mailbox,
    wake: Receiver<()>,
) -> std::io::Result<DriverHandle> {
    if !synthesis.spool_dir.is_dir() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "the spool directory is not a directory",
        ));
    }
    let (go, started) = sync_channel(1);
    let stopping = Arc::new(AtomicBool::new(false));
    let stop = Arc::clone(&stopping);
    let thread = std::thread::Builder::new()
        .name("ai-ttsd-driver".to_owned())
        .spawn(move || {
            if started.recv().is_err() {
                return;
            }
            let retry_after = synthesis.retry_after;
            let mut driver = Driver {
                synthesis,
                mailbox,
                stopping: stop,
                ready: BTreeMap::new(),
                unreported: Vec::new(),
                reports: VecDeque::new(),
            };
            driver.run(&wake, retry_after);
        })?;
    Ok(DriverHandle {
        thread,
        go,
        stopping,
    })
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum Step {
    /// Nothing to do until a request arrives.
    Idle,
    /// Work did progress.
    Progress,
    /// A report waits for the ledger; try again after a wait.
    Retry,
    /// The conductor is gone, or the daemon is stopping.
    Stop,
}

/// How the conductor answered one report.
enum Recorded {
    Yes,
    /// The ledger did not record it; keep it.
    NotYet,
    /// The conductor refused it as no longer applicable; drop it.
    Refused,
    Closed,
}

struct Driver {
    synthesis: Synthesis,
    mailbox: Mailbox,
    stopping: Arc<AtomicBool>,
    /// Sealed spools waiting for the device, by clip.
    ready: BTreeMap<String, Spool>,
    /// Synthesis reports the ledger did not record, with their audio.
    unreported: Vec<Unreported>,
    /// Plain reports the ledger did not record, oldest first.
    reports: VecDeque<Command>,
}

impl Driver {
    fn run(&mut self, wake: &Receiver<()>, retry_after: Duration) {
        let mut wait = retry_after;
        loop {
            let step = self.step();
            if let (Step::Idle | Step::Retry, Some(idle)) = (step, &self.synthesis.on_idle) {
                let _unwatched = idle.send(());
            }
            match step {
                Step::Progress => wait = retry_after,
                Step::Idle => {
                    if wake.recv().is_err() {
                        return;
                    }
                }
                Step::Retry => {
                    if let Err(RecvTimeoutError::Disconnected) = wake.recv_timeout(wait) {
                        return;
                    }
                    wait = wait.saturating_mul(2).min(MAX_RETRY_WAIT);
                }
                Step::Stop => return,
            }
        }
    }

    fn stopping(&self) -> bool {
        self.stopping.load(Ordering::SeqCst)
    }

    fn step(&mut self) -> Step {
        if let Some(step) = self.resend() {
            return step;
        }
        if self.stopping() {
            return Step::Stop;
        }
        let played = self.playback_turn();
        if played == Step::Stop || self.stopping() {
            return Step::Stop;
        }
        let synthesized = self.synthesis_turn();
        self.evict();
        if synthesized == Step::Stop {
            return Step::Stop;
        }
        match (played, synthesized) {
            (Step::Progress, _) | (_, Step::Progress) => Step::Progress,
            (Step::Retry, _) | (_, Step::Retry) => Step::Retry,
            _ => Step::Idle,
        }
    }

    /// Resend kept reports before new work; `None` when none are kept.
    fn resend(&mut self) -> Option<Step> {
        if let Some(report) = self.reports.front().cloned() {
            return Some(match self.report(report) {
                Recorded::Yes | Recorded::Refused => {
                    self.reports.pop_front();
                    Step::Progress
                }
                Recorded::NotYet => Step::Retry,
                Recorded::Closed => Step::Stop,
            });
        }
        let unreported = self.unreported.pop()?;
        let id = clip_of(&unreported.report);
        Some(self.settle(id, retry(unreported, &self.mailbox)))
    }

    fn report(&self, report: Command) -> Recorded {
        match self.mailbox.request(Request::Apply(report)) {
            Ok(Reply::Applied(Ok(_))) => Recorded::Yes,
            Ok(Reply::Applied(Err(DurableError::Ledger(_)))) => Recorded::NotYet,
            Ok(_) => Recorded::Refused,
            Err(_) => Recorded::Closed,
        }
    }

    /// Keep `report` when the ledger did not record it.
    fn send(&mut self, report: Command) -> Step {
        match self.report(report.clone()) {
            Recorded::Yes | Recorded::Refused => Step::Progress,
            Recorded::NotYet => {
                self.reports.push_back(report);
                Step::Retry
            }
            Recorded::Closed => Step::Stop,
        }
    }

    fn synthesis_turn(&mut self) -> Step {
        let id = match self.mailbox.request(Request::NextSynthesis) {
            Ok(Reply::Synthesis(Ok(Some(id)))) => id,
            Ok(Reply::Synthesis(Err(DurableError::Ledger(_)))) => return Step::Retry,
            Ok(_) => return Step::Idle,
            Err(_) => return Step::Stop,
        };
        let stored = match self.mailbox.request(Request::Job(id.clone())) {
            Ok(Reply::Job(Ok(Some(stored)))) => stored,
            // Missing or unreadable: never speak a guess at the text.
            Ok(_) => return self.send(Command::SynthesisFailed(id)),
            Err(_) => return Step::Stop,
        };
        // Composite clips speak their segments in order into one spool.
        let text = if stored.segments.is_empty() {
            stored.text
        } else {
            stored.segments.join("\n\n")
        };
        let job = Job {
            id,
            text,
            voice: stored.voice,
            speed: stored.speed,
            engine: stored.engine.unwrap_or_default(),
        };
        let target = SpoolTarget {
            path: self.spool_path(&job.id),
            capacity_frames: self.synthesis.capacity_frames,
        };
        let finished = synthesize(&job, &mut self.synthesis.engines, &target, &self.mailbox);
        self.settle(job.id, finished)
    }

    fn settle(&mut self, id: String, finished: Finished) -> Step {
        match finished {
            Finished::Ready(spool) => {
                self.ready.insert(id, spool);
                Step::Progress
            }
            Finished::Discarded | Finished::Failed { .. } | Finished::CleanupFailed { .. } => {
                Step::Progress
            }
            Finished::Unreported(unreported) => {
                self.unreported.push(unreported);
                Step::Retry
            }
            Finished::Closed => Step::Stop,
        }
    }

    fn playback_turn(&mut self) -> Step {
        let transfer = match self.mailbox.request(Request::PlanPlayback) {
            Ok(Reply::Planned(Ok(Some(transfer)))) => transfer,
            Ok(Reply::Planned(Err(DurableError::Ledger(_)))) => return Step::Retry,
            Ok(_) => return Step::Idle,
            Err(_) => return Step::Stop,
        };
        let id = match transfer {
            Transfer::Start(id) | Transfer::Restore(id) | Transfer::Preempt { started: id, .. } => {
                id
            }
        };
        let spool = match self.ready.remove(&id) {
            Some(spool) => Ok(spool),
            None => Spool::open_cached(&self.spool_path(&id), self.synthesis.capacity_frames)
                .map_err(|error| error.to_string()),
        };
        let played = spool.and_then(|spool| self.synthesis.sink.play(&id, spool));
        self.send(match played {
            Ok(()) => Command::PlaybackFinished(id),
            Err(_) => Command::PlaybackFailed(id),
        })
    }

    /// Close and remove the spool of every kept clip that is no longer owed.
    fn evict(&mut self) {
        if self.ready.is_empty() {
            return;
        }
        let Ok(Reply::Clips(clips)) = self.mailbox.request(Request::Clips) else {
            return;
        };
        let owed: Vec<String> = clips
            .into_iter()
            .filter(|clip| clip.state == State::Ready)
            .map(|clip| clip.id)
            .collect();
        let gone: Vec<String> = self
            .ready
            .keys()
            .filter(|id| !owed.contains(id))
            .cloned()
            .collect();
        for id in gone {
            drop(self.ready.remove(&id));
            // A file already gone is the wanted end state; another failure
            // leaves the file for cache pruning.
            let _kept = fs::remove_file(self.spool_path(&id));
        }
    }

    fn spool_path(&self, id: &str) -> PathBuf {
        self.synthesis.spool_dir.join(format!("{id}.wav"))
    }
}

/// The clip a synthesis report names.
fn clip_of(report: &Command) -> String {
    match report {
        Command::AudioReady(id) | Command::SynthesisFailed(id) => id.clone(),
        _ => String::new(),
    }
}
