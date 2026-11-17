// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The input and playback queues, lifecycle transitions, and restart recovery.

use rusqlite::types::Value;
use rusqlite::{Connection, params, params_from_iter};

use crate::codec::{
    COLUMNS, SEGMENT_COLUMNS, TERMINAL, priority_name, segment, sensitivity_name, state_name, stem,
    utterance,
};
use crate::{Error, Priority, Result, Segment, Sensitivity, State, Store, Utterance};

/// A submission. The caller mints the `utt_…` identifier.
#[derive(Clone, Debug, PartialEq)]
pub struct NewUtterance {
    /// The new identifier.
    pub id: String,
    /// The submitted text.
    pub text: String,
    /// The voice identifier.
    pub voice: String,
    /// The synthesis speed multiplier.
    pub speed: f64,
    /// Defaults to confidential, as in Python.
    pub sensitivity: Sensitivity,
    /// Defaults to normal.
    pub priority: Priority,
    /// The submitting client.
    pub source: Option<String>,
    /// The utterance this one replays.
    pub replay_of: Option<String>,
    /// The engine the work is bound to.
    pub engine: Option<String>,
    /// Place ahead of every unfinished utterance.
    pub at_head: bool,
    /// Spoken child segments; each must contain non-whitespace text.
    pub segments: Option<Vec<String>>,
    /// Whether the audio is owed to the listener.
    pub playback: bool,
}

impl NewUtterance {
    /// A confidential, normal-priority submission with no segments.
    pub const fn new(id: String, text: String, voice: String, speed: f64) -> Self {
        Self {
            id,
            text,
            voice,
            speed,
            sensitivity: Sensitivity::Confidential,
            priority: Priority::Normal,
            source: None,
            replay_of: None,
            engine: None,
            at_head: false,
            segments: None,
            playback: true,
        }
    }
}

/// Columns a transition may set. `None` leaves the stored value.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Fields {
    /// The failure reason.
    pub error: Option<String>,
    /// The audio duration.
    pub duration_ms: Option<i64>,
    /// The playback position.
    pub played_ms: Option<i64>,
    /// The cached audio file; it also sets the generation identity.
    pub audio_path: Option<String>,
}

/// The queue side of the `utterances` and `utterance_segments` tables.
#[derive(Clone, Copy, Debug)]
pub struct Queue<'a> {
    pub(crate) store: &'a Store,
}

impl Queue<'_> {
    /// Accept text as Queued and return the stored row.
    ///
    /// # Errors
    /// Returns [`Error::Invalid`] for an empty or blank segment list.
    pub fn submit(&self, new: &NewUtterance) -> Result<Utterance> {
        if new.segments.as_ref().is_some_and(|parts| {
            parts.is_empty() || parts.iter().any(|part| part.trim().is_empty())
        }) {
            return Err(Error::Invalid(
                "spoken_segments must contain one or more non-empty segments",
            ));
        }
        let now = self.store.clock.now();
        let db = &self.store.db;
        let transaction = db.unchecked_transaction()?;
        let order_key: f64 = if new.at_head {
            transaction
                .query_row(
                    &format!("SELECT MIN(order_key) FROM utterances WHERE state NOT IN {TERMINAL}"),
                    [],
                    |row| row.get::<_, Option<f64>>(0),
                )?
                .unwrap_or(1.0)
                - 1.0
        } else {
            transaction
                .query_row("SELECT MAX(order_key) FROM utterances", [], |row| {
                    row.get::<_, Option<f64>>(0)
                })?
                .unwrap_or(0.0)
                + 1.0
        };
        transaction.execute(
            &format!(
                "INSERT INTO utterances ({COLUMNS}) VALUES \
                 (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, NULL, ?, ?)"
            ),
            params![
                new.id,
                new.text,
                new.voice,
                new.speed,
                sensitivity_name(new.sensitivity),
                priority_name(new.priority),
                state_name(State::Queued),
                order_key,
                now,
                now,
                new.source,
                new.replay_of,
                new.engine,
                i64::from(new.playback),
            ],
        )?;
        if let Some(parts) = &new.segments {
            let mut insert = transaction.prepare(
                "INSERT INTO utterance_segments \
                 (utterance_id, segment_index, text, state) VALUES (?, ?, ?, ?)",
            )?;
            for (index, part) in (0_i64..).zip(parts) {
                insert.execute(params![new.id, index, part, state_name(State::Queued)])?;
            }
        }
        transaction.commit()?;
        self.get(&new.id)?.ok_or(Error::NotFound)
    }

    /// The utterance with `id`.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] or [`Error::Corrupt`].
    pub fn get(&self, id: &str) -> Result<Option<Utterance>> {
        get(&self.store.db, id)
    }

    /// The ordered children of `id`.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] or [`Error::Corrupt`].
    pub fn segments(&self, id: &str) -> Result<Vec<Segment>> {
        segments_where(
            &self.store.db,
            "utterance_id = ? ORDER BY segment_index",
            params![id],
        )
    }

    /// Submitted, Queued, and Synthesizing utterances in queue order.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] or [`Error::Corrupt`].
    pub fn input(&self) -> Result<Vec<Utterance>> {
        by_states(&self.store.db, INPUT, false)
    }

    /// Ready, Playing, and Paused utterances owed to the listener, in queue order.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] or [`Error::Corrupt`].
    pub fn playback(&self) -> Result<Vec<Utterance>> {
        by_states(&self.store.db, PLAYBACK, true)
    }

    /// Move an utterance through the lifecycle in one transaction.
    ///
    /// A terminal state also cancels every unfinished child, as in Python.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`], [`Error::Transition`], or a write failure.
    pub fn transition(&self, id: &str, to: State, fields: &Fields) -> Result<Utterance> {
        let transaction = self.store.db.unchecked_transaction()?;
        transition(&transaction, self.store.clock.now(), id, to, fields)?;
        transaction.commit()?;
        self.get(id)?.ok_or(Error::NotFound)
    }

    /// Move one child through the same lifecycle as its parent.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`], [`Error::Transition`], or a write failure.
    pub fn transition_segment(
        &self,
        id: &str,
        index: i64,
        to: State,
        fields: &Fields,
    ) -> Result<Segment> {
        let transaction = self.store.db.unchecked_transaction()?;
        transition_segment(&transaction, id, index, to, fields)?;
        transaction.commit()?;
        get_segment(&self.store.db, id, index)?.ok_or(Error::NotFound)
    }

    /// Repair state after a restart, as the Python `Store.recover`.
    ///
    /// Interrupted synthesis returns to Queued and playing work comes back Paused.
    /// Unlike Python, the whole repair is one transaction, so a crash leaves either
    /// the original state or the repaired state. Both converge on the next run.
    ///
    /// # Errors
    /// Returns the first failure; the whole repair then rolls back.
    pub fn recover(&self) -> Result<()> {
        let transaction = self.store.db.unchecked_transaction()?;
        recover(&transaction, self.store.clock.now())?;
        transaction.commit()?;
        Ok(())
    }
}

const INPUT: &[State] = &[State::Submitted, State::Queued, State::Synthesizing];
const PLAYBACK: &[State] = &[State::Ready, State::Playing, State::Paused];

fn state_list(states: &[State]) -> String {
    let names: Vec<String> = states
        .iter()
        .map(|state| format!("'{}'", state_name(*state)))
        .collect();
    format!("({})", names.join(", "))
}

fn get(db: &Connection, id: &str) -> Result<Option<Utterance>> {
    let mut statement = db.prepare(&format!("SELECT {COLUMNS} FROM utterances WHERE id = ?"))?;
    let mut rows = statement.query(params![id])?;
    rows.next()?.map(|row| utterance(row)).transpose()
}

pub(crate) fn utterances_where(
    db: &Connection,
    clause: &str,
    values: impl rusqlite::Params,
) -> Result<Vec<Utterance>> {
    let mut statement = db.prepare(&format!("SELECT {COLUMNS} FROM utterances WHERE {clause}"))?;
    let mut rows = statement.query(values)?;
    let mut found = Vec::new();
    while let Some(row) = rows.next()? {
        found.push(utterance(row)?);
    }
    Ok(found)
}

fn by_states(db: &Connection, states: &[State], playback_only: bool) -> Result<Vec<Utterance>> {
    let playback = if playback_only {
        " AND playback = 1"
    } else {
        ""
    };
    utterances_where(
        db,
        &format!(
            "state IN {}{playback} ORDER BY order_key",
            state_list(states)
        ),
        [],
    )
}

fn segments_where(
    db: &Connection,
    clause: &str,
    values: impl rusqlite::Params,
) -> Result<Vec<Segment>> {
    let mut statement = db.prepare(&format!(
        "SELECT {SEGMENT_COLUMNS} FROM utterance_segments WHERE {clause}"
    ))?;
    let mut rows = statement.query(values)?;
    let mut found = Vec::new();
    while let Some(row) = rows.next()? {
        found.push(segment(row)?);
    }
    Ok(found)
}

fn get_segment(db: &Connection, id: &str, index: i64) -> Result<Option<Segment>> {
    Ok(segments_where(
        db,
        "utterance_id = ? AND segment_index = ?",
        params![id, index],
    )?
    .into_iter()
    .next())
}

/// The `SET` clause and values for the optional transition columns.
fn field_updates(fields: &Fields) -> (String, Vec<Value>) {
    let mut sets = String::new();
    let mut values = Vec::new();
    let generation = fields
        .audio_path
        .as_deref()
        .filter(|path| !path.is_empty())
        .map(stem);
    for (column, value) in [
        ("error", fields.error.clone().map(Value::Text)),
        ("duration_ms", fields.duration_ms.map(Value::Integer)),
        ("played_ms", fields.played_ms.map(Value::Integer)),
        ("audio_path", fields.audio_path.clone().map(Value::Text)),
        ("generation_artifact_id", generation.map(Value::Text)),
    ] {
        if let Some(value) = value {
            sets.push_str(", ");
            sets.push_str(column);
            sets.push_str(" = ?");
            values.push(value);
        }
    }
    (sets, values)
}

fn transition(db: &Connection, now: f64, id: &str, to: State, fields: &Fields) -> Result<()> {
    let current = get(db, id)?.ok_or(Error::NotFound)?;
    current.state.transition(to)?;
    let (sets, mut values) = field_updates(fields);
    let mut all = vec![Value::Text(state_name(to).to_owned()), Value::Real(now)];
    all.append(&mut values);
    all.push(Value::Text(id.to_owned()));
    db.execute(
        &format!("UPDATE utterances SET state = ?, state_changed_at = ?{sets} WHERE id = ?"),
        params_from_iter(all),
    )?;
    if to.is_terminal() {
        db.execute(
            &format!(
                "UPDATE utterance_segments SET state = ? \
                 WHERE utterance_id = ? AND state NOT IN {TERMINAL}"
            ),
            params![state_name(State::Cancelled), id],
        )?;
    }
    Ok(())
}

fn transition_segment(
    db: &Connection,
    id: &str,
    index: i64,
    to: State,
    fields: &Fields,
) -> Result<()> {
    let current = get_segment(db, id, index)?.ok_or(Error::NotFound)?;
    current.state.transition(to)?;
    let (sets, mut values) = field_updates(fields);
    let mut all = vec![Value::Text(state_name(to).to_owned())];
    all.append(&mut values);
    all.push(Value::Text(id.to_owned()));
    all.push(Value::Integer(index));
    db.execute(
        &format!(
            "UPDATE utterance_segments SET state = ?{sets} \
             WHERE utterance_id = ? AND segment_index = ?"
        ),
        params_from_iter(all),
    )?;
    Ok(())
}

fn recover_streaming_jobs(db: &Connection) -> Result<()> {
    let jobs: Vec<(String, Option<i64>)> = db
        .prepare("SELECT utterance_id, segment_index FROM streaming_jobs")?
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
        .collect::<rusqlite::Result<_>>()?;
    for (parent_id, index) in jobs {
        let Some(parent) = get(db, &parent_id)? else {
            continue;
        };
        if parent.state.is_terminal() {
            continue;
        }
        if matches!(parent.state, State::Playing | State::Paused) {
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES ('playback_held', 'true')",
                [],
            )?;
        }
        if let Some(index) = index {
            // A child the listener already skipped is finished.
            db.execute(
                &format!(
                    "UPDATE utterance_segments SET state = 'Queued', audio_path = NULL, \
                     played_ms = NULL WHERE utterance_id = ? AND segment_index = ? \
                     AND state NOT IN {TERMINAL}"
                ),
                params![parent_id, index],
            )?;
            if parent.state == State::Playing {
                db.execute(
                    "UPDATE utterances SET state = 'Paused' WHERE id = ?",
                    params![parent_id],
                )?;
            }
        } else {
            db.execute(
                "UPDATE utterances SET state = 'Queued', audio_path = NULL, \
                 played_ms = NULL WHERE id = ?",
                params![parent_id],
            )?;
        }
    }
    db.execute("DELETE FROM streaming_jobs", [])?;
    Ok(())
}

fn recover(db: &Connection, now: f64) -> Result<()> {
    let none = Fields::default();
    recover_streaming_jobs(db)?;
    for (from, to) in [
        (State::Synthesizing, State::Queued),
        (State::Playing, State::Paused),
    ] {
        let children = segments_where(
            db,
            "state = ? ORDER BY utterance_id, segment_index",
            params![state_name(from)],
        )?;
        for child in children {
            transition_segment(db, &child.utterance_id, child.index, to, &none)?;
        }
    }
    for (from, to) in [
        (State::Synthesizing, State::Queued),
        (State::Playing, State::Paused),
    ] {
        for parent in by_states(db, &[from], false)? {
            transition(db, now, &parent.id, to, &none)?;
        }
    }
    // Child completion may commit before its parent promotion or failure.
    let mut open = by_states(db, INPUT, false)?;
    open.extend(by_states(db, PLAYBACK, true)?);
    for parent in open {
        let children = segments_where(
            db,
            "utterance_id = ? ORDER BY segment_index",
            params![parent.id],
        )?;
        if let Some(failed) = children.iter().find(|child| child.state == State::Failed) {
            if parent.state == State::Queued {
                transition(db, now, &parent.id, State::Synthesizing, &none)?;
            }
            let error = Fields {
                error: Some(format!(
                    "segment failed: {}",
                    failed.error.as_deref().unwrap_or("None")
                )),
                ..Fields::default()
            };
            transition(db, now, &parent.id, State::Failed, &error)?;
        } else if parent.state == State::Paused
            && !children.is_empty()
            && children.iter().all(|child| child.state.is_terminal())
        {
            let played: i64 = db.query_row(
                "SELECT COALESCE(SUM(duration_ms), 0) FROM utterance_segments \
                 WHERE utterance_id = ? AND state = 'Played'",
                params![parent.id],
                |row| row.get(0),
            )?;
            let played = Fields {
                played_ms: Some(played),
                ..Fields::default()
            };
            transition(db, now, &parent.id, State::Played, &played)?;
        } else if parent.state == State::Queued
            && children
                .first()
                .is_some_and(|child| child.state == State::Ready)
        {
            transition(db, now, &parent.id, State::Synthesizing, &none)?;
            transition(db, now, &parent.id, State::Ready, &none)?;
        }
    }
    Ok(())
}
