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

use std::fmt::Write as _;
use std::fs::{self, OpenOptions};
use std::io::{self, Write as _};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

use serde_json::ser::Formatter;
use serde_json::{Map, Value, json};

use crate::evidence::clip_directory;
use crate::private_fs::{ensure_private_directory, ensure_private_file};
use crate::wav::read_format;

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

    /// Save the caller's text and arguments before any processing.
    ///
    /// `request.json` holds `payload` without `text` and `op`, the BLAKE3 of the
    /// text, and the time received.
    ///
    /// # Errors
    /// Fails on an invalid identity, a symbolic link, or an I/O error.
    pub fn submitted(
        &self,
        artifact_id: &str,
        text: &str,
        payload: &Map<String, Value>,
    ) -> io::Result<()> {
        let _guard = self.lock.lock().unwrap_or_else(PoisonError::into_inner);
        let directory = self.directory(artifact_id)?;
        write_private(&directory.join("source.txt"), text.as_bytes())?;
        let arguments: Map<String, Value> = payload
            .iter()
            .filter(|(key, _)| !matches!(key.as_str(), "text" | "op"))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        let request = json!({
            "arguments": arguments,
            "source_blake3": blake3::hash(text.as_bytes()).to_hex().to_string(),
            "received_at": self.clock.wall(),
        });
        write_private(
            &directory.join("request.json"),
            serde_json::to_string_pretty(&request)?.as_bytes(),
        )
    }

    /// Save the identity and numerical diagnostics of a generated WAV.
    ///
    /// Reads 16- and 24-bit integer PCM and 32-bit float WAV files.
    ///
    /// # Errors
    /// Fails on another audio format, an invalid identity, a symbolic link, or
    /// an I/O error. No `audio.json` is written on failure.
    pub fn audio_generated(&self, artifact_id: &str, audio: &Path) -> io::Result<()> {
        let metadata = audio_metadata(audio)?;
        let _guard = self.lock.lock().unwrap_or_else(PoisonError::into_inner);
        let directory = self.directory(artifact_id)?;
        write_private(
            &directory.join("audio.json"),
            serde_json::to_string_pretty(&metadata)?.as_bytes(),
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

/// One sample's bytes; `chunks_exact` guarantees the width.
fn word<const N: usize>(bytes: &[u8]) -> [u8; N] {
    bytes.try_into().unwrap_or([0; N])
}

/// Python's `_CLIPPING_THRESHOLD`, compared as `f32` as `NumPy` does.
const CLIPPING_THRESHOLD: f32 = 0.9999;

/// The identity and numerical diagnostics that Python reads with `soundfile`.
///
/// 16- and 24-bit integer PCM and 32-bit float are read; 32-bit integer PCM is
/// refused because f32 cannot hold its values exactly.
fn audio_metadata(path: &Path) -> io::Result<Value> {
    let bytes = fs::read(path)?;
    let file = fs::File::open(path)?;
    let format = read_format(&file)?;
    let (subtype, decode): (&str, fn(&[u8]) -> f32) =
        match (format.format_tag, format.bits_per_sample) {
            (1, 16) => ("PCM_16", |b| {
                f32::from(i16::from_le_bytes(word(b))) / 32_768.0
            }),
            (1, 24) => ("PCM_24", |b| {
                let [x, y, z] = word(b);
                // Sign-extend through the top byte, then add the two exact parts
                // (high 16 bits, low 8 bits) so the f32 result is exact.
                let value = i32::from_le_bytes([0, x, y, z]) >> 8;
                f32::from(i16::try_from(value >> 8).unwrap_or(0)) / 32_768.0
                    + f32::from(u8::try_from(value & 0xFF).unwrap_or(0)) / 8_388_608.0
            }),
            (3, 32) => ("FLOAT", |b| f32::from_le_bytes(word(b))),
            _ => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "unsupported WAV sample format",
                ));
            }
        };
    let width = usize::from(format.bits_per_sample / 8);
    let block = usize::from(format.block_align);
    let start = usize::try_from(format.data_offset).unwrap_or(usize::MAX);
    let length = usize::try_from(format.data_bytes).unwrap_or(usize::MAX);
    let data = bytes.get(start..).unwrap_or_default();
    let data = data.get(..length.min(data.len())).unwrap_or_default();
    let frames = data.len().checked_div(block).unwrap_or(0);
    let (mut peak, mut clipped, mut nonfinite) = (0.0_f32, 0_u64, 0_u64);
    for sample in data
        .chunks_exact(width)
        .take(frames.saturating_mul(usize::from(format.channels)))
    {
        let value = decode(sample);
        if value.is_finite() {
            peak = peak.max(value.abs());
        } else {
            nonfinite += 1;
        }
        if value.abs() >= CLIPPING_THRESHOLD {
            clipped += 1;
        }
    }
    Ok(json!({
        "blake3": blake3::hash(&bytes).to_hex().to_string(),
        "sha256": sha256_hex(&bytes),
        "sample_rate": format.sample_rate,
        "channels": format.channels,
        "frames": frames,
        "subtype": subtype,
        "peak": f64::from(peak),
        "clipped_samples": clipped,
        "nonfinite_samples": nonfinite,
    }))
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest as _, Sha256};
    Sha256::digest(bytes)
        .iter()
        .fold(String::with_capacity(64), |mut hex, byte| {
            let _ = write!(hex, "{byte:02x}");
            hex
        })
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
