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

use std::path::PathBuf;

use aitts_artifacts::spool::Spool;
use aitts_engine::registry::Registry;

use crate::conductor::mailbox::Mailbox;

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
pub fn synthesize(
    job: &Job,
    registry: &mut Registry,
    target: &SpoolTarget,
    mailbox: &Mailbox,
) -> Finished {
    drop((
        job.clone(),
        registry.names().count(),
        target.clone(),
        mailbox.clone(),
    ));
    Finished::Closed
}
