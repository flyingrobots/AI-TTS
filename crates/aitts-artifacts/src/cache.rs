// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The inventory of generated clips and their explicit removal.
//!
//! This is the Rust form of `aitts.adapters.generated_storage.GeneratedStorage`
//! (`inventory` and `remove`). Each clip directory `<root>/<id>/` and each legacy
//! `<root>/<id>.wav` is one entry. Symbolic links are skipped. An entry is
//! protected when the caller names it or when it holds a `.part` file. Choosing
//! which entries expire is a retention rule and belongs to `aitts-domain`.

use std::collections::BTreeSet;
use std::io;
use std::path::PathBuf;

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
        let _ = (&self.root, protected);
        Err(io::Error::other("not implemented"))
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
        let _ = (ids, protected);
        Err(io::Error::other("not implemented"))
    }
}
