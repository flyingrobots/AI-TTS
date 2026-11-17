// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! This module owns the setup check that installed model files match their pins.
//!
//! Model weights include pickled files, so a file is never loaded before its
//! digest is the pinned digest.

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};

use sha2::{Digest, Sha256};

use crate::catalog;

/// Why setup refused the installed files.
#[derive(Debug)]
pub enum SetupError {
    UnknownModel,
    /// A pinned file is absent or is not a regular file (symbolic links are refused).
    Missing(String),
    /// A file's digest is not its pinned digest.
    DigestMismatch(String),
    /// The user cancelled; nothing was published.
    Cancelled,
    Io(std::io::Error),
}

/// Check every catalog file of `model` under `assets`.
///
/// # Errors
/// See [`verify_files`].
pub fn verify_model_assets(
    model: &str,
    assets: &Path,
    cancel: &AtomicBool,
) -> Result<(), SetupError> {
    let pins = catalog::pinned_digests(model).map_err(|_| SetupError::UnknownModel)?;
    verify_files(assets, &pins, cancel)
}

/// Check that each file in `pins` under `root` has its pinned SHA-256.
///
/// # Errors
/// The first missing or mismatched file, a cancellation, or an I/O failure.
pub fn verify_files(
    root: &Path,
    pins: &BTreeMap<String, String>,
    cancel: &AtomicBool,
) -> Result<(), SetupError> {
    for (name, pinned) in pins {
        let path = root.join(name);
        let regular = path
            .symlink_metadata()
            .is_ok_and(|m| m.file_type().is_file());
        if !regular {
            return Err(SetupError::Missing(name.clone()));
        }
        if &sha256_hex(&path, cancel)? != pinned {
            return Err(SetupError::DigestMismatch(name.clone()));
        }
    }
    Ok(())
}

fn sha256_hex(path: &Path, cancel: &AtomicBool) -> Result<String, SetupError> {
    let mut file = File::open(path).map_err(SetupError::Io)?;
    let mut hasher = Sha256::new();
    let mut block = vec![0_u8; 1 << 16];
    loop {
        // Weights are large: a cancel takes effect between blocks.
        if cancel.load(Ordering::Relaxed) {
            return Err(SetupError::Cancelled);
        }
        let read = file.read(&mut block).map_err(SetupError::Io)?;
        let Some(filled) = block.get(..read) else {
            break;
        };
        if filled.is_empty() {
            break;
        }
        hasher.update(filled);
    }
    let mut hex = String::with_capacity(64);
    for byte in hasher.finalize() {
        // Writing to a String cannot fail.
        let _ = write!(hex, "{byte:02x}");
    }
    Ok(hex)
}
