// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Writing per-clip evidence records, as the Python daemon writes them.
//!
//! This is the Rust form of the `prepare`, `record` and `generated` writers of
//! `aitts.adapters.clip_evidence.ClipEvidence`. Each clip has an owner-only
//! directory `<root>/<artifact_id>/`. `generation.json` and `model.json` hold
//! the generation settings and the loaded model; `synthesis.jsonl` and
//! `playback.jsonl` hold one JSON event per line. A log that would pass the
//! limit (1 MiB, as in Python) is renamed to `<phase>.previous.jsonl` and
//! `logs-truncated.txt` is written. Lines use Python's `json.dumps` separators,
//! so both daemons rotate at the same event.
//!
//! The caller supplies the clock and the process session, so records have no
//! hidden time or identity reads. Unlike Python, write failures are returned.

use std::io;
use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{Map, Value};

/// The Python log limit: 1 MiB per log file.
pub const LOG_LIMIT_BYTES: usize = 1024 * 1024;

/// The time source of event rows.
pub trait EvidenceClock {
    /// Unix seconds, as Python's `time.time()`.
    fn wall(&self) -> f64;
    /// Seconds from an arbitrary origin, as Python's `time.monotonic()`.
    fn monotonic(&self) -> f64;
}

/// The two event logs of a clip.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    /// `synthesis.jsonl`.
    Synthesis,
    /// `playback.jsonl`.
    Playback,
}

/// The generation settings saved before an engine renders a clip.
#[derive(Debug, Clone, PartialEq)]
pub struct GenerationInput<'a> {
    /// The clip identity and directory name.
    pub artifact_id: &'a str,
    /// The utterance the clip belongs to.
    pub utterance_id: &'a str,
    /// The segment of the utterance, if it was split.
    pub segment_index: Option<u64>,
    /// The exact text sent to the engine.
    pub text: &'a str,
    /// The resolved voice.
    pub voice: &'a str,
    /// The resolved speed.
    pub speed: f64,
}

/// Writes evidence records beneath one cache root.
#[derive(Debug)]
pub struct EvidenceRecorder<C> {
    root: PathBuf,
    session: String,
    runtime: Value,
    clock: C,
    log_limit: usize,
    lock: Mutex<()>,
}

impl<C: EvidenceClock> EvidenceRecorder<C> {
    /// Record beneath `root` for one process `session`, with its `runtime` description.
    pub fn new(
        root: impl Into<PathBuf>,
        session: impl Into<String>,
        runtime: Value,
        clock: C,
    ) -> Self {
        Self {
            root: root.into(),
            session: session.into(),
            runtime,
            clock,
            log_limit: LOG_LIMIT_BYTES,
            lock: Mutex::new(()),
        }
    }

    /// Use a log limit other than [`LOG_LIMIT_BYTES`].
    #[must_use]
    pub fn with_log_limit(mut self, bytes: usize) -> Self {
        self.log_limit = bytes;
        self
    }

    /// Save the exact input and the generation settings, then log `started`.
    ///
    /// # Errors
    /// Fails on an invalid identity, a symbolic link, or an I/O error.
    pub fn prepare(&self, input: &GenerationInput<'_>, engine: &str) -> io::Result<()> {
        let _ = (
            input,
            engine,
            &self.root,
            &self.session,
            &self.runtime,
            &self.clock,
            self.log_limit,
            &self.lock,
        );
        Err(io::Error::other("not implemented"))
    }

    /// Append one event with `details` to the `phase` log of `artifact_id`.
    ///
    /// # Errors
    /// Fails on an invalid identity, a symbolic link, or an I/O error.
    pub fn record(
        &self,
        artifact_id: &str,
        phase: Phase,
        event: &str,
        details: &Map<String, Value>,
    ) -> io::Result<()> {
        let _ = (artifact_id, phase, event, details);
        Err(io::Error::other("not implemented"))
    }

    /// Save the model and voice identities that the engine loaded.
    ///
    /// # Errors
    /// Fails on an invalid identity, a symbolic link, or an I/O error.
    pub fn generated(&self, artifact_id: &str, metadata: &Value) -> io::Result<()> {
        let _ = (artifact_id, metadata);
        Err(io::Error::other("not implemented"))
    }
}
