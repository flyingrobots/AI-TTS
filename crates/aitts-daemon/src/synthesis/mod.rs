// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns synthesis of one clip: engine registry to spool to conductor.
//!
//! [`synthesize`] restores a failed engine, streams the clip's audio into a new
//! [`Spool`], and reports the result to the conductor through its [`Mailbox`].
//! Audio for a clip that is no longer owed is removed. Audio is never removed
//! while its report is unrecorded: a report the ledger did not record comes back
//! as [`Finished::Unreported`] with its spool, for [`retry`]. When the conductor
//! stops before answering, the unreported audio is removed.

use std::fmt;
use std::io;
use std::path::PathBuf;

use aitts_artifacts::spool::Spool;
use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::registry::Registry;

use crate::conductor::Command;
use crate::conductor::mailbox::Mailbox;

mod report;

pub use report::retry;

/// One clip the conductor handed to synthesis.
#[derive(Clone, Debug, PartialEq)]
pub struct Job {
    /// The clip.
    pub id: String,
    /// The text to speak.
    pub text: String,
    /// The voice identifier.
    pub voice: String,
    /// The speed multiplier.
    pub speed: f64,
    /// The registered engine name.
    pub engine: String,
}

/// Where a clip's audio goes.
#[derive(Clone, Debug)]
pub struct SpoolTarget {
    /// The WAV path the spool writes.
    pub path: PathBuf,
    /// Frames the spool's read ring holds.
    pub capacity_frames: usize,
}

/// Why synthesis of one clip failed.
#[derive(Debug)]
pub enum SynthesisError {
    /// No engine is registered under the job's engine name.
    NoEngine(String),
    /// The failed engine could not be restored.
    Recover(EngineError),
    /// The spool could not be created; no spool exists.
    CreateSpool(io::Error),
    /// A write to the spool failed; this was the first failure.
    Write(io::Error),
    /// The engine failed while streaming.
    Engine(EngineError),
    /// The spool header could not be sealed.
    Seal(io::Error),
}

impl fmt::Display for SynthesisError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoEngine(name) => write!(formatter, "no engine named {name}"),
            Self::Recover(error) => write!(formatter, "cannot restore the engine: {error}"),
            Self::CreateSpool(error) => write!(formatter, "cannot create the spool: {error}"),
            Self::Write(error) => write!(formatter, "cannot write the spool: {error}"),
            Self::Engine(error) => write!(formatter, "engine failed: {error}"),
            Self::Seal(error) => write!(formatter, "cannot seal the spool: {error}"),
        }
    }
}

impl std::error::Error for SynthesisError {}

/// A report the conductor did not record. Its audio is kept for [`retry`].
#[derive(Debug)]
pub struct Unreported {
    /// The report to send again: `AudioReady` or `SynthesisFailed`.
    pub report: Command,
    /// The sealed or partial spool, if one was created.
    pub spool: Option<Spool>,
    /// The synthesis failure, for a `SynthesisFailed` report.
    pub error: Option<SynthesisError>,
    path: PathBuf,
}

/// How one synthesis ended.
#[derive(Debug)]
pub enum Finished {
    /// The audio is sealed and the conductor recorded the clip as ready.
    Ready(Spool),
    /// The clip was no longer owed; the spool file was removed.
    Discarded,
    /// The conductor recorded the failure. The spool, if created, holds the
    /// frames written before it and reports the error.
    Failed {
        /// The partial spool.
        spool: Option<Spool>,
        /// Why synthesis failed.
        error: SynthesisError,
    },
    /// The ledger did not record the report; nothing was removed.
    Unreported(Unreported),
    /// Audio that is not owed could not be removed.
    CleanupFailed {
        /// The file left behind.
        path: PathBuf,
        /// Why removal failed.
        error: io::Error,
    },
    /// The conductor stopped before answering; the unreported audio was removed.
    Closed,
}

/// Synthesize `job` with its engine from `registry` into `target`, then report it.
///
/// Blocks while the engine streams and while the conductor answers.
pub fn synthesize(
    job: &Job,
    registry: &mut Registry,
    target: &SpoolTarget,
    mailbox: &Mailbox,
) -> Finished {
    let unreported = |report, spool, error| Unreported {
        report,
        spool,
        error,
        path: target.path.clone(),
    };
    let failed =
        |spool, error| unreported(Command::SynthesisFailed(job.id.clone()), spool, Some(error));
    let Some(engine) = registry.engine_mut(&job.engine) else {
        return retry(
            failed(None, SynthesisError::NoEngine(job.engine.clone())),
            mailbox,
        );
    };
    let mut spool = match Spool::create(&target.path, target.capacity_frames) {
        Ok(spool) => spool,
        Err(error) => return retry(failed(None, SynthesisError::CreateSpool(error)), mailbox),
    };
    if let Err(error) = stream_into(job, engine, &mut spool) {
        spool.finish(Some(error.to_string()));
        return retry(failed(Some(spool), error), mailbox);
    }
    spool.finish(None);
    let ready = Command::AudioReady(job.id.clone());
    retry(unreported(ready, Some(spool), None), mailbox)
}

/// Stream into `spool` and seal it. The first failure is the one returned.
fn stream_into(
    job: &Job,
    engine: &mut dyn Engine,
    spool: &mut Spool,
) -> Result<(), SynthesisError> {
    let request = SpeechRequest {
        text: &job.text,
        voice: &job.voice,
        speed: job.speed,
    };
    let mut write_error = None;
    // The engine is drained after a write failure, so its worker stays in step.
    let streamed = engine.stream(&request, &mut |pcm| {
        if write_error.is_none() {
            write_error = spool.append(pcm).err();
        }
    });
    streamed.map_err(SynthesisError::Engine)?;
    if let Some(error) = write_error {
        return Err(SynthesisError::Write(error));
    }
    spool.seal().map(|_| ()).map_err(SynthesisError::Seal)
}
