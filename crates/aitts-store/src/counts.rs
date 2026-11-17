// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the per-state row counts that status and metrics report.

use crate::codec::state;
use crate::{Result, State, Store};

impl Store {
    /// Utterance rows per lifecycle state, in lifecycle order, omitting empty states.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] or [`crate::Error::Corrupt`] when a read fails.
    pub fn counts(&self) -> Result<Vec<(State, u64)>> {
        let mut statement = self
            .db
            .prepare("SELECT state, COUNT(*) FROM utterances GROUP BY state")?;
        let mut rows = statement.query([])?;
        let mut counts = Vec::new();
        while let Some(row) = rows.next()? {
            let name: String = row.get(0)?;
            let count: i64 = row.get(1)?;
            let count =
                u64::try_from(count).map_err(|_| crate::Error::Corrupt { column: "state" })?;
            counts.push((state(&name)?, count));
        }
        counts.sort_by_key(|(known, _)| crate::codec::state_rank(*known));
        Ok(counts)
    }
}
