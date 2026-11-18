// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns writing new queue positions, as the Python `reorder_pending`.

use rusqlite::params;

use crate::queue::Queue;
use crate::{Error, Result};

impl Queue<'_> {
    /// Set each named utterance's order key in one transaction.
    ///
    /// # Errors
    /// Returns [`crate::Error::NotFound`] for an unknown id, or a write failure;
    /// the whole change then rolls back.
    pub fn reorder(&self, keys: &[(String, f64)]) -> Result<()> {
        let transaction = self.store.db.unchecked_transaction()?;
        for (id, order) in keys {
            let changed = transaction.execute(
                "UPDATE utterances SET order_key = ? WHERE id = ?",
                params![order, id],
            )?;
            if changed != 1 {
                return Err(Error::NotFound);
            }
        }
        transaction.commit()?;
        Ok(())
    }
}
