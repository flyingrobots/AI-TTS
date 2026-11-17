// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Terminal utterances. Search is issue #5 and is not here.

use rusqlite::params;

use crate::codec::TERMINAL;
use crate::queue::utterances_where;
use crate::{Result, Store, Utterance};

/// Terminal rows of the `utterances` table.
#[derive(Clone, Copy, Debug)]
pub struct History<'a> {
    pub(crate) store: &'a Store,
}

impl History<'_> {
    /// Terminal utterances, newest first, submitted before the `before` utterance when given.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] or [`crate::Error::Corrupt`] when a read fails.
    pub fn list(&self, limit: u32, before: Option<&str>) -> Result<Vec<Utterance>> {
        let db = &self.store.db;
        let anchor = match before {
            Some(id) => self.store.queue().get(id)?.map(|found| found.submitted_at),
            None => None,
        };
        match anchor {
            Some(submitted_at) => utterances_where(
                db,
                &format!(
                    "state IN {TERMINAL} AND submitted_at < ? ORDER BY submitted_at DESC LIMIT ?"
                ),
                params![submitted_at, limit],
            ),
            None => utterances_where(
                db,
                &format!("state IN {TERMINAL} ORDER BY submitted_at DESC LIMIT ?"),
                params![limit],
            ),
        }
    }

    /// Remove one terminal record. Cached audio is not touched.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the write fails.
    pub fn remove(&self, id: &str) -> Result<bool> {
        let removed = self.store.db.execute(
            &format!("DELETE FROM utterances WHERE id = ? AND state IN {TERMINAL}"),
            params![id],
        )?;
        Ok(removed == 1)
    }

    /// Remove every terminal record and return the count.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the write fails.
    pub fn clear(&self) -> Result<usize> {
        Ok(self.store.db.execute(
            &format!("DELETE FROM utterances WHERE state IN {TERMINAL}"),
            [],
        )?)
    }
}
