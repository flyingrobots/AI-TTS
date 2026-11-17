// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The Python daemon's schema and its additive migrations, in the Python order.
//!
//! The Python daemon does not set `PRAGMA user_version`; it detects each migration from
//! the columns present. This module does the same and never writes `user_version`.

use rusqlite::Connection;

use crate::Result;
use crate::codec::stem;

/// Byte-identical to `aitts.store._SCHEMA`, so `sqlite_master` matches.
const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS utterances (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    voice TEXT NOT NULL,
    speed REAL NOT NULL,
    sensitivity TEXT NOT NULL,
    priority TEXT NOT NULL,
    state TEXT NOT NULL,
    order_key REAL NOT NULL,
    submitted_at REAL NOT NULL,
    state_changed_at REAL NOT NULL,
    source TEXT,
    error TEXT,
    duration_ms INTEGER,
    played_ms INTEGER,
    audio_path TEXT,
    replay_of TEXT,
    engine TEXT,
    playback INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_utterances_state ON utterances(state);
CREATE INDEX IF NOT EXISTS idx_utterances_order ON utterances(order_key);
CREATE TABLE IF NOT EXISTS utterance_segments (
    utterance_id TEXT NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    duration_ms INTEGER,
    played_ms INTEGER,
    audio_path TEXT,
    PRIMARY KEY (utterance_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_utterance_segments_state ON utterance_segments(state);
CREATE TABLE IF NOT EXISTS streaming_jobs (
    artifact_id TEXT PRIMARY KEY,
    utterance_id TEXT NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
    segment_index INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_assignments (
    source TEXT PRIMARY KEY,
    voice TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    assigned_at REAL NOT NULL
);
";

/// One additive column migration, applied when its column is absent.
struct Migration {
    table: &'static str,
    column: &'static str,
    definition: &'static str,
    /// Fill generation identity from the audio file name, as Python does.
    backfill_generation: bool,
}

const MIGRATIONS: [Migration; 4] = [
    Migration {
        table: "utterances",
        column: "generation_artifact_id",
        definition: "TEXT",
        backfill_generation: true,
    },
    Migration {
        table: "utterance_segments",
        column: "generation_artifact_id",
        definition: "TEXT",
        backfill_generation: true,
    },
    Migration {
        table: "utterances",
        column: "engine",
        definition: "TEXT",
        backfill_generation: false,
    },
    Migration {
        table: "utterances",
        column: "playback",
        definition: "INTEGER NOT NULL DEFAULT 1",
        backfill_generation: false,
    },
];

fn has_column(db: &Connection, table: &str, column: &str) -> Result<bool> {
    let mut statement = db.prepare(&format!("PRAGMA table_info({table})"))?;
    let names = statement.query_map([], |row| row.get::<_, String>(1))?;
    for name in names {
        if name? == column {
            return Ok(true);
        }
    }
    Ok(false)
}

fn backfill_generation(db: &Connection, table: &str) -> Result<()> {
    let rows: Vec<(i64, String)> = db
        .prepare(&format!(
            "SELECT rowid, audio_path FROM {table} \
             WHERE generation_artifact_id IS NULL AND audio_path IS NOT NULL"
        ))?
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
        .collect::<rusqlite::Result<_>>()?;
    let mut update = db.prepare(&format!(
        "UPDATE {table} SET generation_artifact_id = ? WHERE rowid = ?"
    ))?;
    for (rowid, path) in rows {
        update.execute(rusqlite::params![stem(&path), rowid])?;
    }
    Ok(())
}

/// Create missing tables and columns in one transaction.
pub(crate) fn migrate(db: &Connection) -> Result<()> {
    // `journal_mode` reports the resulting mode as a row.
    db.query_row("PRAGMA journal_mode=WAL", [], |_| Ok(()))?;
    db.execute_batch("PRAGMA foreign_keys=ON")?;
    let transaction = db.unchecked_transaction()?;
    transaction.execute_batch(SCHEMA)?;
    for migration in &MIGRATIONS {
        if !has_column(&transaction, migration.table, migration.column)? {
            transaction.execute_batch(&format!(
                "ALTER TABLE {} ADD COLUMN {} {}",
                migration.table, migration.column, migration.definition
            ))?;
        }
        if migration.backfill_generation {
            backfill_generation(&transaction, migration.table)?;
        }
    }
    transaction.commit()?;
    Ok(())
}
