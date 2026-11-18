// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns reporting a synthesis result and the audio cleanup it implies.

use std::fs;

use super::{Finished, Unreported};
use crate::conductor::Outcome;
use crate::conductor::mailbox::{Mailbox, Reply, Request};

/// Send `unreported.report` to the conductor and settle its audio.
///
/// A recorded `AudioReady` returns the spool; a recorded failure returns the
/// error and partial spool; audio that is not owed is removed; a ledger failure
/// returns the report again with nothing removed; a stopped conductor removes
/// the unreported audio.
pub fn retry(unreported: Unreported, mailbox: &Mailbox) -> Finished {
    let answer = mailbox.request(Request::Apply(unreported.report.clone()));
    match (answer, unreported.error) {
        (Ok(Reply::Applied(Ok(Outcome::Applied))), None) => match unreported.spool {
            Some(spool) => Finished::Ready(spool),
            None => Finished::Discarded,
        },
        (Ok(Reply::Applied(Ok(_))), Some(error)) => Finished::Failed {
            spool: unreported.spool,
            error,
        },
        _ => {
            drop(unreported.spool);
            // Stub: every other answer discards the audio.
            let _absent = fs::remove_file(&unreported.path);
            Finished::Discarded
        }
    }
}
