// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the cached-audio byte total that `metrics` reports.
//!
//! It counts what the Python `FileAudioCache.inventory` counts: regular, non-link
//! `.wav` files directly under the cache root or one directory below it. It only
//! reads; a missing cache directory holds zero bytes.

use std::fs::{self, DirEntry};
use std::path::Path;

/// Total bytes of cached WAV files under `root`.
pub(crate) fn cached_bytes(root: &Path) -> u64 {
    let Ok(entries) = fs::read_dir(root) else {
        return 0;
    };
    entries
        .flatten()
        .map(|entry| match entry.file_type() {
            Ok(kind) if kind.is_dir() => fs::read_dir(entry.path()).map_or(0, |inner| {
                inner
                    .flatten()
                    .map(|file| wav_bytes(&file))
                    .fold(0, u64::saturating_add)
            }),
            _ => wav_bytes(&entry),
        })
        .fold(0, u64::saturating_add)
}

fn wav_bytes(entry: &DirEntry) -> u64 {
    let is_wav = entry
        .path()
        .extension()
        .is_some_and(|extension| extension == "wav");
    match entry.file_type() {
        Ok(kind) if kind.is_file() && is_wav => entry.metadata().map_or(0, |found| found.len()),
        _ => 0,
    }
}
