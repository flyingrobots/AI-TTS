// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The inventory of generated clips and their explicit removal.
//!
//! This is the Rust form of `aitts.adapters.generated_storage.GeneratedStorage`
//! (`inventory` and `remove`). Each clip directory `<root>/<id>/` and each legacy
//! `<root>/<id>.wav` is one entry. Symbolic links are skipped. An entry is
//! protected when the caller names it or when it holds a `.part` file. Choosing
//! which entries expire is a retention rule and belongs to `aitts-domain`.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{self, ErrorKind};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

/// The number of characters of `source.txt` in a preview, as in Python.
pub const PREVIEW_CHARS: usize = 160;

/// One clip in the cache.
#[derive(Debug, Clone, PartialEq)]
pub struct InventoryRow {
    /// The clip identity.
    pub id: String,
    /// The bytes of all its regular files.
    pub bytes: u64,
    /// The newest modification time of its files, in Unix seconds.
    pub modified_at: f64,
    /// The caller protects it, or it is still being written.
    pub protected: bool,
    /// The start of its source text on one line, or its identity.
    pub preview: String,
}

/// The result of [`GeneratedStorage::remove`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Removal {
    /// Entries deleted.
    pub removed: usize,
    /// Entries asked for but protected.
    pub protected: usize,
    /// Entries whose deletion failed.
    pub failed: usize,
}

/// The generated clips beneath one cache root.
#[derive(Debug, Clone)]
pub struct GeneratedStorage {
    root: PathBuf,
}

impl GeneratedStorage {
    /// Manage the clips beneath `root`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// List every clip, newest first. A missing root is an empty cache.
    ///
    /// # Errors
    /// Fails on an I/O error other than a missing root.
    pub fn inventory(&self, protected: &BTreeSet<String>) -> io::Result<Vec<InventoryRow>> {
        let members = match fs::read_dir(&self.root) {
            Ok(members) => members,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(Vec::new()),
            Err(error) => return Err(error),
        };
        let mut rows: BTreeMap<String, InventoryRow> = BTreeMap::new();
        for member in members {
            let path = member?.path();
            let Some((id, files)) = entry_files(&path)? else {
                continue;
            };
            let row = rows.entry(id.clone()).or_insert_with(|| InventoryRow {
                protected: protected.contains(&id),
                preview: id.clone(),
                id,
                bytes: 0,
                modified_at: 0.0,
            });
            for file in files {
                let Ok(info) = fs::metadata(&file) else {
                    continue;
                };
                row.bytes += info.len();
                let modified = info
                    .modified()?
                    .duration_since(UNIX_EPOCH)
                    .map_or(0.0, |since| since.as_secs_f64());
                row.modified_at = row.modified_at.max(modified);
                let name = file
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("");
                #[allow(
                    clippy::case_sensitive_file_extension_comparisons,
                    reason = "Python's `name.endswith(\".part\")` is case-sensitive"
                )]
                let writing = name.ends_with(".part");
                if writing {
                    row.protected = true;
                }
                if name == "source.txt" {
                    row.preview = preview(&fs::read(&file)?);
                }
            }
        }
        let mut rows: Vec<InventoryRow> = rows.into_values().collect();
        rows.sort_by(|a, b| b.modified_at.total_cmp(&a.modified_at));
        Ok(rows)
    }

    /// Delete the named clips that are not protected.
    ///
    /// # Errors
    /// Fails when the inventory cannot be read. A failed deletion is counted.
    pub fn remove(
        &self,
        ids: &BTreeSet<String>,
        protected: &BTreeSet<String>,
    ) -> io::Result<Removal> {
        let mut removal = Removal {
            removed: 0,
            protected: 0,
            failed: 0,
        };
        for row in self.inventory(protected)? {
            if !ids.contains(&row.id) {
                continue;
            }
            if row.protected {
                removal.protected += 1;
                continue;
            }
            match self.delete(&row.id) {
                Ok(()) => removal.removed += 1,
                Err(_) => removal.failed += 1,
            }
        }
        Ok(removal)
    }

    fn delete(&self, id: &str) -> io::Result<()> {
        let directory = self.root.join(id);
        if fs::symlink_metadata(&directory).is_ok_and(|meta| meta.is_dir()) {
            fs::remove_dir_all(&directory)?;
        }
        let legacy = self.root.join(format!("{id}.wav"));
        match fs::symlink_metadata(&legacy) {
            Ok(meta) if !meta.file_type().is_symlink() => fs::remove_file(&legacy),
            _ => Ok(()),
        }
    }
}

/// The identity and regular files of one cache member, or `None` to skip it.
fn entry_files(path: &Path) -> io::Result<Option<(String, Vec<PathBuf>)>> {
    let kind = fs::symlink_metadata(path)?.file_type();
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("");
    if kind.is_dir() {
        let mut files = Vec::new();
        for member in fs::read_dir(path)? {
            let member = member?.path();
            if fs::symlink_metadata(&member)?.file_type().is_file() {
                files.push(member);
            }
        }
        return Ok(Some((name.to_owned(), files)));
    }
    match name.strip_suffix(".wav") {
        Some(id) if kind.is_file() && !id.is_empty() => {
            Ok(Some((id.to_owned(), vec![path.to_path_buf()])))
        }
        _ => Ok(None),
    }
}

/// Python's `open(encoding="utf-8", errors="replace").read(160)` with newlines
/// translated, then each newline replaced by a space.
fn preview(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes)
        .replace("\r\n", "\n")
        .replace('\r', "\n")
        .chars()
        .take(PREVIEW_CHARS)
        .map(|c| if c == '\n' { ' ' } else { c })
        .collect()
}
