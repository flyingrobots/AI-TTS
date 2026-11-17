// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Export of per-clip evidence to a ZIP, entry for entry as the Python daemon does.
//!
//! This is the Rust form of `aitts.adapters.clip_evidence.ClipEvidence.export`.
//! The archive holds, for each clip, the evidence files found in
//! `<root>/<artifact_id>/` and its cached audio, then `manifest.json`, the item's
//! `source.txt`, and `README.txt`. The caller supplies the export time and the
//! runtime description, so the manifest has no hidden clock or machine reads.

use std::fmt::Write as _;
use std::fs::{self, File, OpenOptions};
use std::io::{self, ErrorKind, Read as _, Write as _};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};
use sha2::{Digest as _, Sha256};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

use crate::private_fs::PRIVATE_FILE_MODE;

/// The evidence files of one clip, in archive order.
const EVIDENCE_FILES: [&str; 10] = [
    "source.txt",
    "request.json",
    "audio.json",
    "generation.json",
    "model.json",
    "synthesis.previous.jsonl",
    "synthesis.jsonl",
    "playback.previous.jsonl",
    "playback.jsonl",
    "logs-truncated.txt",
];
/// Files whose absence the manifest reports.
const EXPECTED_FILES: [&str; 3] = ["generation.json", "synthesis.jsonl", "playback.jsonl"];
const README: &str = "AI-TTS local audio evidence\n\n\
    Contains the selected spoken content. Share only when you choose.\n\
    Each clips/ directory contains audio and synthesis/playback JSONL logs.\n\
    Times are Unix seconds; monotonic readings share a process_session.\n\
    Playback sessions identify replays. See manifest.json for missing evidence.\n\
    Generation-time versions live in generation.json, not export_runtime.\n";

/// The result of one export.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExportReport {
    /// The archive written.
    pub path: PathBuf,
    /// The missing-evidence warnings, also in `manifest.json`.
    pub warnings: Vec<String>,
}

/// The evidence directories beneath one cache root.
#[derive(Debug, Clone)]
pub struct ClipEvidence {
    root: PathBuf,
}

impl ClipEvidence {
    /// Use the evidence beneath `root`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// Write a new owner-only ZIP at `destination`. Never overwrites a file.
    ///
    /// `item` is the history item; each of `clips` has `artifact_id`, `text` and
    /// an optional `audio_path`. A failed export leaves no partial archive.
    ///
    /// # Errors
    /// Fails when `destination` is not an absolute `.zip` path or already exists,
    /// when a clip identity is invalid, when audio is outside the root, or on an
    /// I/O error.
    pub fn export(
        &self,
        destination: &Path,
        item: &Value,
        clips: &[Value],
        exported_at: f64,
        runtime: &Value,
    ) -> io::Result<ExportReport> {
        let is_zip = destination
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("zip"));
        if !destination.is_absolute() || !is_zip {
            return Err(invalid("choose an absolute .zip destination"));
        }
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(PRIVATE_FILE_MODE)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(destination)?;
        match self.write_archive(file, item, clips, exported_at, runtime) {
            Ok(warnings) => Ok(ExportReport {
                path: destination.to_path_buf(),
                warnings,
            }),
            Err(error) => {
                let _ = fs::remove_file(destination);
                Err(error)
            }
        }
    }

    fn write_archive(
        &self,
        file: File,
        item: &Value,
        clips: &[Value],
        exported_at: f64,
        runtime: &Value,
    ) -> io::Result<Vec<String>> {
        let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
        let mut archive = ZipWriter::new(file);
        let mut warnings = Vec::new();
        let mut entries = Vec::new();
        for clip in clips {
            let clip = clip
                .as_object()
                .ok_or_else(|| invalid("clip must be an object"))?;
            let id = text_of(clip.get("artifact_id"));
            let mut entry: Map<String, Value> = clip
                .iter()
                .filter(|(key, _)| *key != "audio_path")
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect();
            let folder = format!("clips/{id}");
            let directory = self.directory_path(&id)?;
            for name in EVIDENCE_FILES {
                let path = directory.join(name);
                if is_regular_file(&path) {
                    archive.start_file(format!("{folder}/{name}"), options)?;
                    archive.write_all(&fs::read(&path)?)?;
                } else if EXPECTED_FILES.contains(&name) {
                    warnings.push(format!("{id}: {name} was not captured"));
                }
            }
            if directory.join("logs-truncated.txt").exists() {
                warnings.push(format!("{id}: older log events were rotated out"));
            }
            // Legacy clips still export their exact source text.
            if !directory.join("source.txt").is_file() {
                archive.start_file(format!("{folder}/source.txt"), options)?;
                archive.write_all(text_of(clip.get("text")).as_bytes())?;
            }
            let audio = clip
                .get("audio_path")
                .and_then(Value::as_str)
                .filter(|path| !path.is_empty())
                .map(PathBuf::from);
            match audio.filter(|path| is_regular_file(path)) {
                None => {
                    entry.insert("audio_available".to_owned(), json!(false));
                    warnings.push(format!("{id}: cached audio is missing"));
                }
                Some(path) => {
                    if !path.canonicalize()?.starts_with(self.root.canonicalize()?) {
                        return Err(invalid("audio is outside the owned cache"));
                    }
                    match File::open(&path) {
                        Ok(source) => {
                            archive.start_file(format!("{folder}/audio.wav"), options)?;
                            let (sha256, blake3, bytes) = copy_hashed(source, &mut archive)?;
                            entry.insert("audio_available".to_owned(), json!(true));
                            entry.insert("audio_sha256".to_owned(), json!(sha256));
                            entry.insert("audio_blake3".to_owned(), json!(blake3));
                            entry.insert("audio_bytes".to_owned(), json!(bytes));
                        }
                        Err(error) if error.kind() == ErrorKind::NotFound => {
                            entry.insert("audio_available".to_owned(), json!(false));
                            warnings.push(format!("{id}: audio was evicted during export"));
                        }
                        Err(error) => return Err(error),
                    }
                }
            }
            entries.push(Value::Object(entry));
        }
        let manifest = json!({
            "format_version": 1,
            "exported_at": exported_at,
            "export_runtime": runtime,
            "item": item,
            "clips": entries,
            "warnings": warnings,
        });
        archive.start_file("manifest.json", options)?;
        archive.write_all(serde_json::to_string_pretty(&manifest)?.as_bytes())?;
        archive.start_file("source.txt", options)?;
        archive.write_all(text_of(item.get("text")).as_bytes())?;
        archive.start_file("README.txt", options)?;
        archive.write_all(README.as_bytes())?;
        archive.finish()?;
        Ok(warnings)
    }

    fn directory_path(&self, id: &str) -> io::Result<PathBuf> {
        clip_directory(&self.root, id)
    }
}

/// Resolve a flat clip identity beneath `root`, refusing symbolic links.
pub(crate) fn clip_directory(root: &Path, id: &str) -> io::Result<PathBuf> {
    if Path::new(id).file_name().is_none_or(|name| name != id) {
        return Err(invalid("invalid artifact identity"));
    }
    let directory = root.join(id);
    if is_symlink(root) || is_symlink(&directory) {
        return Err(invalid("evidence directories must not be symlinks"));
    }
    Ok(directory)
}

/// Python's `str(value)` for the string and missing cases the daemon passes.
fn text_of(value: Option<&Value>) -> String {
    match value {
        None => String::new(),
        Some(Value::String(text)) => text.clone(),
        Some(other) => other.to_string(),
    }
}

fn is_regular_file(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|meta| meta.is_file())
}

fn is_symlink(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|meta| meta.file_type().is_symlink())
}

fn copy_hashed(mut source: File, target: &mut impl io::Write) -> io::Result<(String, String, u64)> {
    let mut sha256 = Sha256::new();
    let mut blake3 = blake3::Hasher::new();
    let mut bytes = 0u64;
    let mut block = vec![0; 1024 * 1024];
    loop {
        let count = source.read(&mut block)?;
        let Some(chunk) = block.get(..count).filter(|chunk| !chunk.is_empty()) else {
            break;
        };
        sha256.update(chunk);
        blake3.update(chunk);
        target.write_all(chunk)?;
        bytes += u64::try_from(count).unwrap_or(u64::MAX);
    }
    let sha256 = sha256
        .finalize()
        .iter()
        .fold(String::with_capacity(64), |mut hex, byte| {
            let _ = write!(hex, "{byte:02x}");
            hex
        });
    Ok((sha256, blake3.finalize().to_hex().to_string(), bytes))
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(ErrorKind::InvalidInput, message)
}
