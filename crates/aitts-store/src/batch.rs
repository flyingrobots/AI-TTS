// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns writing several queue changes as one all-or-nothing save.

use rusqlite::{Connection, params};

use crate::queue::{Fields, Queue, transition};
use crate::{Error, Result, State};

impl Queue<'_> {
    /// Set each named utterance's order key in one transaction, as Python
    /// `reorder_pending`.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] for an unknown id, or a write failure; the
    /// whole change then rolls back.
    pub fn reorder(&self, keys: &[(String, f64)]) -> Result<()> {
        self.save(&[], keys).map(|_stamp| ())
    }

    /// Apply lifecycle transitions, then order keys, in one transaction. A
    /// failure at any row leaves every row unchanged.
    ///
    /// Returns the time stamped on every transition, in Unix seconds.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`], [`Error::Transition`], or a write failure;
    /// the whole save then rolls back.
    pub fn save(&self, transitions: &[(String, State)], keys: &[(String, f64)]) -> Result<f64> {
        let transaction = self.store.db.unchecked_transaction()?;
        let now = self.store.clock.now();
        for (id, to) in transitions {
            transition(&transaction, now, id, *to, &Fields::default())?;
        }
        write_keys(&transaction, keys)?;
        transaction.commit()?;
        Ok(now)
    }
}

fn write_keys(db: &Connection, keys: &[(String, f64)]) -> Result<()> {
    for (id, order) in keys {
        let changed = db.execute(
            "UPDATE utterances SET order_key = ? WHERE id = ?",
            params![order, id],
        )?;
        if changed != 1 {
            return Err(Error::NotFound);
        }
    }
    Ok(())
}
