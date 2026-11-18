// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns reporting a synthesis result and the audio cleanup it implies.

use std::fs;
use std::io;
use std::path::Path;

use aitts_artifacts::spool::Spool;

use super::{Finished, Unreported};
use crate::conductor::Outcome;
use crate::conductor::durable::DurableError;
use crate::conductor::mailbox::{Mailbox, Reply, Request};

/// Send `unreported.report` to the conductor and settle its audio.
///
/// A recorded `AudioReady` returns the spool; a recorded failure returns the
/// error and partial spool; audio that is not owed is removed; a ledger failure
/// returns the report again with nothing removed; a stopped conductor removes
/// the unreported audio.
pub fn retry(unreported: Unreported, mailbox: &Mailbox) -> Finished {
    let Unreported {
        report,
        spool,
        error,
        path,
    } = unreported;
    match mailbox.request(Request::Apply(report.clone())) {
        Ok(Reply::Applied(Ok(Outcome::Applied))) => match (spool, error) {
            (spool, Some(error)) => Finished::Failed { spool, error },
            (Some(spool), None) => Finished::Ready(spool),
            (None, None) => Finished::Discarded,
        },
        // Not owed any more (cancelled, or refused as illegal): remove the audio.
        Ok(Reply::Applied(
            Ok(Outcome::Discarded | Outcome::Cleared(_)) | Err(DurableError::Refused(_)),
        )) => remove(spool, &path, Finished::Discarded),
        // Not recorded: keep everything for another attempt.
        Ok(Reply::Applied(Err(DurableError::Ledger(_)))) => Finished::Unreported(Unreported {
            report,
            spool,
            error,
            path,
        }),
        // The conductor stopped, or answered out of contract: nothing will own
        // this audio, so remove it.
        Ok(_) | Err(_) => remove(spool, &path, Finished::Closed),
    }
}

/// Remove `path`, closing `spool` first. A file already gone counts as removed.
fn remove(spool: Option<Spool>, path: &Path, removed: Finished) -> Finished {
    drop(spool);
    match fs::remove_file(path) {
        Ok(()) => removed,
        Err(error) if error.kind() == io::ErrorKind::NotFound => removed,
        Err(error) => Finished::CleanupFailed {
            path: path.to_path_buf(),
            error,
        },
    }
}
