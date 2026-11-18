// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the loop that drives synthesis ahead of playback.
//!
//! One driver thread asks the conductor for the next clip to synthesize, runs
//! [`crate::synthesis::synthesize`], and plays every device transfer the
//! conductor plans through a [`Sink`]. It sleeps on a wake signal that the API
//! thread sends after each request, and ends when the daemon stops.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::mpsc::{Receiver, Sender};
use std::thread::JoinHandle;
use std::time::Duration;

use aitts_artifacts::spool::Spool;
use aitts_engine::registry::Registry;
use aitts_store::{Store, SystemClock};

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

/// Start the driver thread over its own store connection at `database`.
pub(crate) fn spawn(
    synthesis: Synthesis,
    database: PathBuf,
    mailbox: Mailbox,
    wake: Receiver<()>,
) -> std::io::Result<JoinHandle<()>> {
    std::thread::Builder::new()
        .name("ai-ttsd-driver".to_owned())
        .spawn(move || {
            let Ok(store) = Store::open(&database, SystemClock) else {
                return;
            };
            let mut driver = Driver {
                synthesis,
                store,
                mailbox,
                ready: BTreeMap::new(),
                unreported: Vec::new(),
            };
            // Work until nothing is left, then sleep until the next request.
            loop {
                match driver.step() {
                    Step::Progress => {}
                    Step::Idle => {
                        if wake.recv().is_err() {
                            return;
                        }
                    }
                    Step::Stop => return,
                }
            }
        })
}

enum Step {
    Progress,
    Idle,
    Stop,
}

struct Driver {
    synthesis: Synthesis,
    store: Store,
    mailbox: Mailbox,
    /// Sealed spools waiting for the device, by clip.
    ready: BTreeMap<String, Spool>,
    /// Reports the ledger did not record, retried before new work.
    unreported: Vec<Unreported>,
}

impl Driver {
    fn step(&mut self) -> Step {
        if let Some(unreported) = self.unreported.pop() {
            return self.settle(retry(unreported, &self.mailbox));
        }
        match self.mailbox.request(Request::NextSynthesis) {
            Ok(Reply::Synthesis(Ok(Some(id)))) => return self.synthesize(&id),
            Ok(_) => {}
            Err(_) => return Step::Stop,
        }
        match self.mailbox.request(Request::PlanPlayback) {
            Ok(Reply::Planned(Ok(Some(transfer)))) => self.play(transfer),
            Ok(_) => Step::Idle,
            Err(_) => Step::Stop,
        }
    }

    fn synthesize(&mut self, id: &str) -> Step {
        let Ok(Some(row)) = self.store.queue().get(id) else {
            // The row is gone; report the failure so the clip leaves synthesis.
            let failed = Request::Apply(Command::SynthesisFailed(id.to_owned()));
            return if self.mailbox.request(failed).is_ok() {
                Step::Progress
            } else {
                Step::Stop
            };
        };
        let segments = self.store.queue().segments(id).unwrap_or_default();
        // Composite clips speak their segments in order into one spool.
        let text = if segments.is_empty() {
            row.text
        } else {
            segments
                .into_iter()
                .map(|segment| segment.text)
                .collect::<Vec<_>>()
                .join("\n\n")
        };
        let job = Job {
            id: row.id,
            text,
            voice: row.voice,
            speed: row.speed,
            engine: row.engine.unwrap_or_default(),
        };
        let target = SpoolTarget {
            path: self.synthesis.spool_dir.join(format!("{}.wav", job.id)),
            capacity_frames: self.synthesis.capacity_frames,
        };
        let finished = synthesize(&job, &mut self.synthesis.engines, &target, &self.mailbox);
        if let Finished::Ready(spool) = finished {
            self.ready.insert(job.id, spool);
            return Step::Progress;
        }
        self.settle(finished)
    }

    fn settle(&mut self, finished: Finished) -> Step {
        match finished {
            Finished::Ready(_)
            | Finished::Discarded
            | Finished::Failed { .. }
            | Finished::CleanupFailed { .. } => Step::Progress,
            Finished::Unreported(unreported) => {
                self.unreported.push(unreported);
                // Do not spin on a failing ledger; wait for the next request.
                Step::Idle
            }
            Finished::Closed => Step::Stop,
        }
    }

    fn play(&mut self, transfer: Transfer) -> Step {
        let id = match transfer {
            Transfer::Start(id) | Transfer::Restore(id) | Transfer::Preempt { started: id, .. } => {
                id
            }
        };
        let spool = match self.ready.remove(&id) {
            Some(spool) => Ok(spool),
            None => Spool::open_cached(
                &self.synthesis.spool_dir.join(format!("{id}.wav")),
                self.synthesis.capacity_frames,
            )
            .map_err(|error| error.to_string()),
        };
        let played = spool.and_then(|spool| self.synthesis.sink.play(&id, spool));
        let report = match played {
            Ok(()) => Command::PlaybackFinished(id),
            Err(_) => Command::PlaybackFailed(id),
        };
        match self.mailbox.request(Request::Apply(report)) {
            Ok(_) => Step::Progress,
            Err(_) => Step::Stop,
        }
    }
}
