// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Text values and row layouts shared with the Python `aitts.store` module.

use rusqlite::Row;

use crate::{Error, Priority, Result, Segment, Sensitivity, State, Utterance};

pub(crate) const COLUMNS: &str = "id, text, voice, speed, sensitivity, priority, state, \
    order_key, submitted_at, state_changed_at, source, error, duration_ms, played_ms, \
    audio_path, replay_of, generation_artifact_id, engine, playback";

pub(crate) const SEGMENT_COLUMNS: &str = "utterance_id, segment_index, text, state, error, \
    duration_ms, played_ms, audio_path, generation_artifact_id";

/// The SQL list of terminal state values, in Python `TERMINAL` order.
pub(crate) const TERMINAL: &str = "('Played', 'Skipped', 'Cancelled', 'Failed')";

const STATES: [(State, &str); 10] = [
    (State::Submitted, "Submitted"),
    (State::Queued, "Queued"),
    (State::Synthesizing, "Synthesizing"),
    (State::Ready, "Ready"),
    (State::Playing, "Playing"),
    (State::Paused, "Paused"),
    (State::Played, "Played"),
    (State::Skipped, "Skipped"),
    (State::Cancelled, "Cancelled"),
    (State::Failed, "Failed"),
];

pub(crate) fn state_name(state: State) -> &'static str {
    STATES
        .iter()
        .find(|(known, _)| *known == state)
        .map_or("", |(_, name)| name)
}

fn state(value: &str) -> Result<State> {
    STATES
        .iter()
        .find(|(_, name)| *name == value)
        .map(|(known, _)| *known)
        .ok_or(Error::Corrupt { column: "state" })
}

pub(crate) const fn sensitivity_name(sensitivity: Sensitivity) -> &'static str {
    match sensitivity {
        Sensitivity::Public => "public",
        Sensitivity::Internal => "internal",
        Sensitivity::Confidential => "confidential",
    }
}

fn sensitivity(value: &str) -> Result<Sensitivity> {
    match value {
        "public" => Ok(Sensitivity::Public),
        "internal" => Ok(Sensitivity::Internal),
        "confidential" => Ok(Sensitivity::Confidential),
        _ => Err(Error::Corrupt {
            column: "sensitivity",
        }),
    }
}

pub(crate) const fn priority_name(priority: Priority) -> &'static str {
    match priority {
        Priority::Normal => "normal",
        Priority::Urgent => "urgent",
        Priority::Preempt => "preempt",
    }
}

fn priority(value: &str) -> Result<Priority> {
    match value {
        "normal" => Ok(Priority::Normal),
        "urgent" => Ok(Priority::Urgent),
        "preempt" => Ok(Priority::Preempt),
        _ => Err(Error::Corrupt { column: "priority" }),
    }
}

pub(crate) fn utterance(row: &Row<'_>) -> Result<Utterance> {
    Ok(Utterance {
        id: row.get(0)?,
        text: row.get(1)?,
        voice: row.get(2)?,
        speed: row.get(3)?,
        sensitivity: sensitivity(&row.get::<_, String>(4)?)?,
        priority: priority(&row.get::<_, String>(5)?)?,
        state: state(&row.get::<_, String>(6)?)?,
        order_key: row.get(7)?,
        submitted_at: row.get(8)?,
        state_changed_at: row.get(9)?,
        source: row.get(10)?,
        error: row.get(11)?,
        duration_ms: row.get(12)?,
        played_ms: row.get(13)?,
        audio_path: row.get(14)?,
        replay_of: row.get(15)?,
        generation_artifact_id: row.get(16)?,
        engine: row.get(17)?,
        playback: row.get::<_, i64>(18)? != 0,
    })
}

pub(crate) fn segment(row: &Row<'_>) -> Result<Segment> {
    Ok(Segment {
        utterance_id: row.get(0)?,
        index: row.get(1)?,
        text: row.get(2)?,
        state: state(&row.get::<_, String>(3)?)?,
        error: row.get(4)?,
        duration_ms: row.get(5)?,
        played_ms: row.get(6)?,
        audio_path: row.get(7)?,
        generation_artifact_id: row.get(8)?,
    })
}

/// The Python `Path(audio_path).stem` used as generation identity.
pub(crate) fn stem(path: &str) -> String {
    std::path::Path::new(path)
        .file_stem()
        .map_or_else(String::new, |stem| stem.to_string_lossy().into_owned())
}
