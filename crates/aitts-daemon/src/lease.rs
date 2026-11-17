// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the process-lifetime socket lease.
//!
//! It takes the same advisory `flock` on `<socket>.lock` as the Python
//! `ExclusiveFileLease`, so a Rust and a Python daemon also exclude each other.
//! The lock file is never removed: unlinking it would let a competing owner lock a
//! different file at the same path.

use std::fs::{File, OpenOptions, TryLockError};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

use crate::runtime::StartError;

/// An exclusive lease, released when dropped.
#[derive(Debug)]
pub(crate) struct Lease {
    _file: File,
}

/// The lock file beside `socket`, as the Python daemon names it.
pub(crate) fn lock_path(socket: &Path) -> PathBuf {
    let mut name = socket.as_os_str().to_owned();
    name.push(".lock");
    PathBuf::from(name)
}

/// Take the lease without waiting.
///
/// # Errors
/// [`StartError::AlreadyRunning`] when another process holds it, and
/// [`StartError::SocketOccupied`] when the lock path is a symbolic link.
pub(crate) fn acquire(socket: &Path) -> Result<Lease, StartError> {
    let path = lock_path(socket);
    if std::fs::symlink_metadata(&path).is_ok_and(|found| found.file_type().is_symlink()) {
        return Err(StartError::SocketOccupied);
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(&path)
        .map_err(StartError::Io)?;
    match file.try_lock() {
        Ok(()) => Ok(Lease { _file: file }),
        Err(TryLockError::WouldBlock) => Err(StartError::AlreadyRunning),
        Err(TryLockError::Error(error)) => Err(StartError::Io(error)),
    }
}
