// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Persisted string settings. Typed parsing lives in `aitts_domain::settings`.

use rusqlite::{OptionalExtension, params};

use crate::{Result, Store};

/// The `settings` table.
#[derive(Clone, Copy, Debug)]
pub struct Settings<'a> {
    pub(crate) store: &'a Store,
}

impl Settings<'_> {
    /// Read a setting, falling back to `default`.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the read fails.
    pub fn get(&self, key: &str, default: &str) -> Result<String> {
        Ok(self
            .store
            .db
            .query_row(
                "SELECT value FROM settings WHERE key = ?",
                params![key],
                |row| row.get(0),
            )
            .optional()?
            .unwrap_or_else(|| default.to_owned()))
    }

    /// Whether a setting has been explicitly persisted.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the read fails.
    pub fn has(&self, key: &str) -> Result<bool> {
        Ok(self
            .store
            .db
            .query_row("SELECT 1 FROM settings WHERE key = ?", params![key], |_| {
                Ok(())
            })
            .optional()?
            .is_some())
    }

    /// Every persisted setting, ordered by key.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the read fails.
    pub fn all(&self) -> Result<Vec<(String, String)>> {
        Ok(self
            .store
            .db
            .prepare("SELECT key, value FROM settings ORDER BY key")?
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
            .collect::<rusqlite::Result<_>>()?)
    }

    /// Write a setting.
    ///
    /// # Errors
    /// Returns [`crate::Error::Sqlite`] when the write fails.
    pub fn set(&self, key: &str, value: &str) -> Result<()> {
        self.store.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) \
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params![key, value],
        )?;
        Ok(())
    }
}
