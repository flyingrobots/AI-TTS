// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Synthesized WAV files, written to a hidden candidate and published atomically.
//!
//! The layout is the Python one: `<root>/<id>/<id>.wav` is the published audio,
//! and `<root>/<id>/.<id>.wav.part` is the candidate an engine writes. A reader
//! never sees a partial file at the published path, because only a complete
//! candidate is renamed onto it. [`AudioArtifacts::prepare`] deletes candidates
//! that a crash left behind.

use std::fs;
use std::io::{self, ErrorKind};
use std::path::{Path, PathBuf};

use crate::private_fs::{create_private_file, ensure_private_directory, secure_existing_file};

/// The synthesized audio files beneath one cache root.
#[derive(Debug, Clone)]
pub struct AudioArtifacts {
    root: PathBuf,
}

impl AudioArtifacts {
    /// Manage the audio files beneath `root`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// Create the root, make the known files owner-only, and delete crash candidates.
    ///
    /// Symbolic links are skipped and their targets are not changed.
    ///
    /// # Errors
    /// Fails on an I/O error, or when the root is a symbolic link.
    pub fn prepare(&self) -> io::Result<()> {
        ensure_private_directory(&self.root, true)?;
        for entry in fs::read_dir(&self.root)? {
            let member = entry?.path();
            let kind = fs::symlink_metadata(&member)?.file_type();
            if kind.is_dir() {
                ensure_private_directory(&member, true)?;
                for child in fs::read_dir(&member)? {
                    let child = child?.path();
                    if is_candidate(&child) {
                        Self::discard(&child);
                    } else if fs::symlink_metadata(&child)?.file_type().is_file() {
                        secure_existing_file(&child)?;
                    }
                }
            } else if is_candidate(&member) {
                Self::discard(&member);
            } else if kind.is_file() {
                secure_existing_file(&member)?;
            }
        }
        Ok(())
    }

    /// Return a new, empty, owner-only candidate path for `id`.
    ///
    /// # Errors
    /// Fails when `id` is not one path component, or on an I/O error.
    pub fn target(&self, id: &str) -> io::Result<PathBuf> {
        let candidate = self.candidate_path(id)?;
        ensure_private_directory(&self.directory(id)?, true)?;
        if !Self::discard(&candidate) {
            return Err(io::Error::other("could not prepare synthesis candidate"));
        }
        create_private_file(&candidate)?;
        Ok(candidate)
    }

    /// Rename the complete candidate of `id` onto its published path.
    ///
    /// The rename is atomic: a reader of the published path sees the old file or
    /// the new file, never a partial one.
    ///
    /// # Errors
    /// Fails when `candidate` is not the candidate of `id`, or on an I/O error.
    pub fn publish(&self, id: &str, candidate: &Path) -> io::Result<PathBuf> {
        if candidate != self.candidate_path(id)? {
            return Err(io::Error::new(
                ErrorKind::InvalidInput,
                "unexpected synthesis candidate",
            ));
        }
        secure_existing_file(candidate)?;
        let published = self.directory(id)?.join(format!("{id}.wav"));
        fs::rename(candidate, &published)?;
        Ok(published)
    }

    /// Return true when `path` is a non-empty regular file, not a link.
    pub fn is_usable(path: &Path) -> bool {
        fs::symlink_metadata(path).is_ok_and(|meta| meta.is_file() && meta.len() > 0)
    }

    /// Delete `path` if it exists. Returns `false` when the delete fails.
    pub fn discard(path: &Path) -> bool {
        match fs::remove_file(path) {
            Ok(()) => true,
            Err(error) => error.kind() == ErrorKind::NotFound,
        }
    }

    fn candidate_path(&self, id: &str) -> io::Result<PathBuf> {
        Ok(self.directory(id)?.join(format!(".{id}.wav.part")))
    }

    fn directory(&self, id: &str) -> io::Result<PathBuf> {
        let single = Path::new(id).file_name().is_some_and(|name| name == id);
        if !single {
            return Err(io::Error::new(
                ErrorKind::InvalidInput,
                "invalid artifact identity",
            ));
        }
        Ok(self.root.join(id))
    }
}

fn is_candidate(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.starts_with('.') && name.ends_with(".wav.part"))
}
