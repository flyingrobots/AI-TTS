// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns synthesis of one clip: engine registry to spool to conductor.
//!
//! [`synthesize`] streams a clip's audio from its engine into a new [`Spool`], then
//! reports the result to the conductor through its [`Mailbox`]. The conductor
//! decides whether the audio is still owed: audio for a clip cancelled during
//! synthesis is discarded and its spool file removed. A failed engine finishes the
//! spool with the error, so a reader receives only the frames that were written,
//! and the clip is marked failed.

use std::fs;
use std::path::PathBuf;

use aitts_artifacts::spool::Spool;
use aitts_engine::engine::{Engine, SpeechRequest};
use aitts_engine::registry::Registry;

use crate::conductor::mailbox::{Mailbox, Reply, Request, SendError};
use crate::conductor::{Command, Outcome};

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

/// How one synthesis ended.
#[derive(Debug)]
pub enum Finished {
    /// The audio is sealed and the conductor marked the clip ready.
    Ready(Spool),
    /// The clip was no longer owed; the spool file was removed.
    Discarded,
    /// The engine failed; the spool holds the frames written before the failure
    /// and reports the error, and the conductor marked the clip failed.
    Failed {
        /// The partial spool.
        spool: Option<Spool>,
        /// Why synthesis failed.
        error: String,
    },
    /// The conductor stopped before answering; nothing more is owed.
    Closed,
}

/// Synthesize `job` with its engine from `registry` into `target`, then report it.
///
/// Blocks while the engine streams and while the conductor answers. A report the
/// conductor refuses (the clip is no longer owed) discards the audio like a cancel.
pub fn synthesize(
    job: &Job,
    registry: &mut Registry,
    target: &SpoolTarget,
    mailbox: &Mailbox,
) -> Finished {
    let Some(engine) = registry.engine_mut(&job.engine) else {
        return failed(
            job,
            None,
            format!("no engine named {}", job.engine),
            mailbox,
        );
    };
    let mut spool = match Spool::create(&target.path, target.capacity_frames) {
        Ok(spool) => spool,
        Err(error) => return failed(job, None, format!("cannot create spool: {error}"), mailbox),
    };
    if let Err(error) = stream_into(job, engine, &mut spool) {
        spool.finish(Some(error.clone()));
        return failed(job, Some(spool), error, mailbox);
    }
    spool.finish(None);
    match mailbox.request(Request::Apply(Command::AudioReady(job.id.clone()))) {
        Ok(Reply::Applied(Ok(Outcome::Applied))) => Finished::Ready(spool),
        Ok(_) => {
            drop(spool);
            // A file already gone is the wanted end state.
            let _absent = fs::remove_file(&target.path);
            Finished::Discarded
        }
        Err(SendError::Closed | SendError::Full) => Finished::Closed,
    }
}

/// Stream into `spool` and seal it; the first engine or write failure wins.
fn stream_into(job: &Job, engine: &mut dyn Engine, spool: &mut Spool) -> Result<(), String> {
    let request = SpeechRequest {
        text: &job.text,
        voice: &job.voice,
        speed: job.speed,
    };
    let mut write_error = None;
    let streamed = engine.stream(&request, &mut |pcm| {
        if write_error.is_none() {
            write_error = spool.append(pcm).err();
        }
    });
    streamed.map_err(|error| error.to_string())?;
    if let Some(error) = write_error {
        return Err(format!("cannot write spool: {error}"));
    }
    spool
        .seal()
        .map(|_| ())
        .map_err(|error| format!("cannot seal spool: {error}"))
}

fn failed(job: &Job, spool: Option<Spool>, error: String, mailbox: &Mailbox) -> Finished {
    match mailbox.request(Request::Apply(Command::SynthesisFailed(job.id.clone()))) {
        Ok(_) => Finished::Failed { spool, error },
        Err(_) => Finished::Closed,
    }
}
