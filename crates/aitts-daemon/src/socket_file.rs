// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the socket path: stale-socket removal and a private bind.

use std::io::ErrorKind;
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;

use crate::runtime::StartError;

/// Bind `path` with mode 0600, after removing a socket no process serves.
///
/// The caller must hold the lease, so no other daemon can bind between the
/// liveness probe and the bind.
///
/// # Errors
/// [`StartError::SocketOccupied`] for a non-socket entry or symbolic link,
/// [`StartError::LiveSocket`] when a server answers, and [`StartError::Io`].
pub(crate) fn bind_private(path: &Path) -> Result<UnixListener, StartError> {
    remove_stale(path)?;
    let listener = UnixListener::bind(path).map_err(StartError::Io)?;
    if let Err(error) = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)) {
        let _removed = std::fs::remove_file(path);
        return Err(StartError::Io(error));
    }
    Ok(listener)
}

fn remove_stale(path: &Path) -> Result<(), StartError> {
    let found = match std::fs::symlink_metadata(path) {
        Ok(found) => found,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(StartError::Io(error)),
    };
    if !found.file_type().is_socket() {
        return Err(StartError::SocketOccupied);
    }
    match UnixStream::connect(path) {
        Ok(_live) => Err(StartError::LiveSocket),
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::ConnectionRefused | ErrorKind::NotFound
            ) =>
        {
            match std::fs::remove_file(path) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
                Err(error) => Err(StartError::Io(error)),
            }
        }
        Err(error) => Err(StartError::Io(error)),
    }
}
