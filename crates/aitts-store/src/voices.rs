// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Voice assignments per client source. Allocation rules live in `aitts_domain::voices`.

use std::collections::BTreeSet;

use rusqlite::{OptionalExtension, Row, params};

use crate::{Error, Result, Store};

const SELECT: &str = "SELECT source, voice, pinned, assigned_at FROM voice_assignments";

fn assignment(row: &Row<'_>) -> rusqlite::Result<VoiceAssignment> {
    Ok(VoiceAssignment {
        source: row.get(0)?,
        voice: row.get(1)?,
        pinned: row.get::<_, i64>(2)? != 0,
        assigned_at: row.get(3)?,
    })
}

/// One row of the `voice_assignments` table.
#[derive(Clone, Debug, PartialEq)]
pub struct VoiceAssignment {
    /// The client source.
    pub source: String,
    /// The held voice.
    pub voice: String,
    /// Whether the listener chose it; a pin outranks an automatic claim.
    pub pinned: bool,
    /// Assignment time, in Unix seconds.
    pub assigned_at: f64,
}

/// The `voice_assignments` table.
#[derive(Clone, Copy, Debug)]
pub struct Voices<'a> {
    pub(crate) store: &'a Store,
}

impl Voices<'_> {
    /// The voice held by `source`.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the read fails.
    pub fn get(&self, source: &str) -> Result<Option<VoiceAssignment>> {
        Ok(self
            .store
            .db
            .query_row(
                &format!("{SELECT} WHERE source = ?"),
                params![source],
                assignment,
            )
            .optional()?)
    }

    /// Every assignment, oldest first.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the read fails.
    pub fn list(&self) -> Result<Vec<VoiceAssignment>> {
        Ok(self
            .store
            .db
            .prepare(&format!("{SELECT} ORDER BY assigned_at, source"))?
            .query_map([], assignment)?
            .collect::<rusqlite::Result<_>>()?)
    }

    /// Voices already held by some source.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the read fails.
    pub fn claimed(&self) -> Result<BTreeSet<String>> {
        Ok(self
            .store
            .db
            .prepare("SELECT DISTINCT voice FROM voice_assignments")?
            .query_map([], |row| row.get(0))?
            .collect::<rusqlite::Result<_>>()?)
    }

    /// Record an automatic claim. A pinned assignment is never replaced.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the write fails.
    pub fn claim(&self, source: &str, voice: &str) -> Result<VoiceAssignment> {
        self.store.db.execute(
            "INSERT INTO voice_assignments (source, voice, pinned, assigned_at) \
             VALUES (?, ?, 0, ?) ON CONFLICT(source) DO UPDATE SET \
             voice = excluded.voice, assigned_at = excluded.assigned_at WHERE pinned = 0",
            params![source, voice, self.store.clock.now()],
        )?;
        self.get(source)?.ok_or(Error::NotFound)
    }

    /// Record the listener's own choice, which outranks any claim.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the write fails.
    pub fn pin(&self, source: &str, voice: &str) -> Result<VoiceAssignment> {
        self.store.db.execute(
            "INSERT INTO voice_assignments (source, voice, pinned, assigned_at) \
             VALUES (?, ?, 1, ?) ON CONFLICT(source) DO UPDATE SET voice = excluded.voice, \
             pinned = 1, assigned_at = excluded.assigned_at",
            params![source, voice, self.store.clock.now()],
        )?;
        self.get(source)?.ok_or(Error::NotFound)
    }

    /// Forget one assignment so the source claims again.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the write fails.
    pub fn release(&self, source: &str) -> Result<bool> {
        Ok(self.store.db.execute(
            "DELETE FROM voice_assignments WHERE source = ?",
            params![source],
        )? > 0)
    }
}
