// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Export of per-clip evidence to a ZIP, entry for entry as the Python daemon does.
//!
//! This is the Rust form of `aitts.adapters.clip_evidence.ClipEvidence.export`.
//! The archive holds, for each clip, the evidence files found in
//! `<root>/<artifact_id>/` and its cached audio, then `manifest.json`, the item's
//! `source.txt`, and `README.txt`. The caller supplies the export time and the
//! runtime description, so the manifest has no hidden clock or machine reads.

use std::io;
use std::path::{Path, PathBuf};

use serde_json::Value;

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
        let _ = (&self.root, destination, item, clips, exported_at, runtime);
        Err(io::Error::other("not implemented"))
    }
}
