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

use std::fs::{self, OpenOptions};
use std::io::{self, Write as _};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

use serde_json::ser::Formatter;
use serde_json::{Map, Value, json};

use crate::evidence::clip_directory;
use crate::private_fs::{ensure_private_directory, ensure_private_file};

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
        let _guard = self.lock.lock().unwrap_or_else(PoisonError::into_inner);
        let directory = self.directory(input.artifact_id)?;
        write_private(&directory.join("source.txt"), input.text.as_bytes())?;
        let generation = json!({
            "artifact_id": input.artifact_id,
            "utterance_id": input.utterance_id,
            "segment_index": input.segment_index,
            "voice": input.voice,
            "speed": input.speed,
            "engine": engine,
            "captured_at": self.clock.wall(),
            "runtime": self.runtime,
        });
        write_private(
            &directory.join("generation.json"),
            serde_json::to_string_pretty(&generation)?.as_bytes(),
        )?;
        self.append(input.artifact_id, Phase::Synthesis, "started", &Map::new())
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
        let _guard = self.lock.lock().unwrap_or_else(PoisonError::into_inner);
        self.append(artifact_id, phase, event, details)
    }

    /// Save the model and voice identities that the engine loaded.
    ///
    /// # Errors
    /// Fails on an invalid identity, a symbolic link, or an I/O error.
    pub fn generated(&self, artifact_id: &str, metadata: &Value) -> io::Result<()> {
        let _guard = self.lock.lock().unwrap_or_else(PoisonError::into_inner);
        let directory = self.directory(artifact_id)?;
        write_private(
            &directory.join("model.json"),
            serde_json::to_string_pretty(metadata)?.as_bytes(),
        )
    }

    fn append(
        &self,
        artifact_id: &str,
        phase: Phase,
        event: &str,
        details: &Map<String, Value>,
    ) -> io::Result<()> {
        let at = self.clock.wall();
        let mut row = Map::new();
        row.insert("at".to_owned(), json!(at));
        row.insert("monotonic".to_owned(), json!(self.clock.monotonic()));
        row.insert("process_session".to_owned(), json!(self.session));
        row.insert("event".to_owned(), json!(event));
        row.extend(
            details
                .iter()
                .map(|(key, value)| (key.clone(), value.clone())),
        );
        let mut encoded = python_line(&Value::Object(row))?;
        if encoded.len() > self.log_limit {
            encoded = python_line(&json!({
                "at": at,
                "event": "oversized_event_omitted",
                "process_session": self.session,
            }))?;
        }
        let directory = self.directory(artifact_id)?;
        let name = match phase {
            Phase::Synthesis => "synthesis",
            Phase::Playback => "playback",
        };
        let path = directory.join(format!("{name}.jsonl"));
        ensure_private_file(&path)?;
        let size = usize::try_from(fs::symlink_metadata(&path)?.len()).unwrap_or(usize::MAX);
        if size.saturating_add(encoded.len()) > self.log_limit {
            fs::rename(&path, directory.join(format!("{name}.previous.jsonl")))?;
            ensure_private_file(&path)?;
            write_private(
                &directory.join("logs-truncated.txt"),
                b"Earlier events were rotated out.\n",
            )?;
        }
        OpenOptions::new()
            .append(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&path)?
            .write_all(&encoded)
    }

    fn directory(&self, artifact_id: &str) -> io::Result<PathBuf> {
        let directory = clip_directory(&self.root, artifact_id)?;
        ensure_private_directory(&self.root, true)?;
        ensure_private_directory(&directory, true)?;
        Ok(directory)
    }
}

/// Replace a private file's contents without following a link.
fn write_private(path: &Path, content: &[u8]) -> io::Result<()> {
    ensure_private_file(path)?;
    OpenOptions::new()
        .write(true)
        .truncate(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?
        .write_all(content)
}

/// One log line as Python's `json.dumps(row, ensure_ascii=False) + "\n"` spaces it.
fn python_line(value: &Value) -> io::Result<Vec<u8>> {
    let mut out = Vec::new();
    let mut serializer = serde_json::Serializer::with_formatter(&mut out, PythonFormatter);
    serde::Serialize::serialize(value, &mut serializer).map_err(io::Error::other)?;
    out.push(b'\n');
    Ok(out)
}

/// Python's default `json.dumps` separators: `", "` and `": "`.
struct PythonFormatter;

impl Formatter for PythonFormatter {
    fn begin_array_value<W: ?Sized + io::Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }
    fn begin_object_key<W: ?Sized + io::Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }
    fn begin_object_value<W: ?Sized + io::Write>(&mut self, writer: &mut W) -> io::Result<()> {
        writer.write_all(b": ")
    }
}
