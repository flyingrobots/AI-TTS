// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Owner-only files and directories, opened without following the last link.
//!
//! Each function opens the path with `O_NOFOLLOW`, checks the open descriptor,
//! and sets the mode through that descriptor. A symbolic link, a FIFO, or any
//! other non-regular file in place of a private file is refused without blocking.

use std::fs::{self, File, OpenOptions, Permissions};
use std::io::{self, ErrorKind};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::Path;

/// The mode of each private directory.
pub const PRIVATE_DIRECTORY_MODE: u32 = 0o700;
/// The mode of each private file.
pub const PRIVATE_FILE_MODE: u32 = 0o600;

const NO_FOLLOW: i32 = libc::O_NOFOLLOW | libc::O_CLOEXEC;

/// Create `path` and its parents as owner-only directories, then check it.
///
/// An existing directory is set to owner-only when `normalize_existing` is true.
///
/// # Errors
/// Fails when `path` is a symbolic link or not a directory, or on an I/O error.
pub fn ensure_private_directory(path: &Path, normalize_existing: bool) -> io::Result<()> {
    let created = match fs::DirBuilder::new()
        .recursive(false)
        .mode(PRIVATE_DIRECTORY_MODE)
        .create(path)
    {
        Ok(()) => true,
        Err(error) if error.kind() == ErrorKind::AlreadyExists => false,
        Err(error) if error.kind() == ErrorKind::NotFound => {
            fs::DirBuilder::new()
                .recursive(true)
                .mode(PRIVATE_DIRECTORY_MODE)
                .create(path)?;
            true
        }
        Err(error) => return Err(error),
    };
    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | NO_FOLLOW)
        .open(path)?;
    if !directory.metadata()?.is_dir() {
        return Err(io::Error::new(
            ErrorKind::NotADirectory,
            "private directory path is not a directory",
        ));
    }
    if created || normalize_existing {
        directory.set_permissions(Permissions::from_mode(PRIVATE_DIRECTORY_MODE))?;
    }
    Ok(())
}

/// Create or normalize one owner-only regular file.
///
/// # Errors
/// Fails when `path` is a symbolic link or not a regular file, or on an I/O error.
pub fn ensure_private_file(path: &Path) -> io::Result<()> {
    secure(path, OpenOptions::new().read(true).write(true).create(true)).map(drop)
}

/// Create one new, empty, owner-only regular file. An existing path is an error.
///
/// # Errors
/// Fails when anything exists at `path`, or on an I/O error.
pub fn create_private_file(path: &Path) -> io::Result<File> {
    secure(path, OpenOptions::new().write(true).create_new(true))
}

/// Make an existing regular file owner-only. Returns `false` when it is absent.
///
/// # Errors
/// Fails when `path` is a symbolic link or not a regular file, or on an I/O error.
pub fn secure_existing_file(path: &Path) -> io::Result<bool> {
    match secure(path, OpenOptions::new().read(true)) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

fn secure(path: &Path, options: &mut OpenOptions) -> io::Result<File> {
    let file = options
        .mode(PRIVATE_FILE_MODE)
        .custom_flags(NO_FOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::new(
            ErrorKind::InvalidInput,
            "private file path is not a regular file",
        ));
    }
    file.set_permissions(Permissions::from_mode(PRIVATE_FILE_MODE))?;
    Ok(file)
}
