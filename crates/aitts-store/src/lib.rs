// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The AI-TTS state database, shared byte-for-byte with the Python daemon.
//!
//! [`Store::open`] opens or creates the same SQLite file and schema as the Python
//! `aitts.store.Store`. Four small interfaces expose it: [`Store::queue`],
//! [`Store::history`], [`Store::settings`], and [`Store::voices`]. The crate never
//! changes the schema version.

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

mod codec;
mod counts;
pub mod history;
pub mod queue;
mod schema;
pub mod settings;
pub mod voices;

use core::fmt;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

pub use aitts_domain::sensitivity::Sensitivity;
pub use aitts_domain::utterance::{InvalidTransition, State};
use rusqlite::Connection;

/// The source of wall-clock seconds stored in timestamp columns.
pub trait Clock {
    /// Seconds since the Unix epoch, as the Python daemon's `time.time()`.
    fn now(&self) -> f64;
}

/// The operating system clock.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> f64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0.0, |elapsed| elapsed.as_secs_f64())
    }
}

/// Queue placement, stored as the Python `Priority` value.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Priority {
    /// Ordinary order.
    Normal,
    /// Queues ahead of ordinary work.
    Urgent,
    /// Interrupts playback when audio is ready.
    Preempt,
}

/// One row of the `utterances` table.
#[derive(Clone, Debug, PartialEq)]
pub struct Utterance {
    /// The `utt_…` identifier.
    pub id: String,
    /// The submitted text.
    pub text: String,
    /// The voice identifier.
    pub voice: String,
    /// The synthesis speed multiplier.
    pub speed: f64,
    /// The immutable disclosure policy.
    pub sensitivity: Sensitivity,
    /// The queue placement.
    pub priority: Priority,
    /// The lifecycle state.
    pub state: State,
    /// The position in queue order.
    pub order_key: f64,
    /// Submission time, in Unix seconds.
    pub submitted_at: f64,
    /// Last state change time, in Unix seconds.
    pub state_changed_at: f64,
    /// The submitting client, when known.
    pub source: Option<String>,
    /// The failure reason, when failed.
    pub error: Option<String>,
    /// The audio duration.
    pub duration_ms: Option<i64>,
    /// The playback position.
    pub played_ms: Option<i64>,
    /// The cached audio file.
    pub audio_path: Option<String>,
    /// The utterance this one replays.
    pub replay_of: Option<String>,
    /// The generation that produced the audio.
    pub generation_artifact_id: Option<String>,
    /// The engine the work is bound to. Old databases have no value.
    pub engine: Option<String>,
    /// Whether the audio is owed to the listener.
    pub playback: bool,
}

/// One row of the `utterance_segments` table: a child of a composite utterance.
#[derive(Clone, Debug, PartialEq)]
pub struct Segment {
    /// The parent utterance.
    pub utterance_id: String,
    /// The zero-based position in the parent.
    pub index: i64,
    /// The spoken text of this child.
    pub text: String,
    /// The lifecycle state.
    pub state: State,
    /// The failure reason, when failed.
    pub error: Option<String>,
    /// The audio duration.
    pub duration_ms: Option<i64>,
    /// The playback position.
    pub played_ms: Option<i64>,
    /// The cached audio file.
    pub audio_path: Option<String>,
    /// The generation that produced the audio.
    pub generation_artifact_id: Option<String>,
}

/// A refused or failed store operation. It carries no submitted text.
#[derive(Debug)]
pub enum Error {
    /// The SQLite driver failed. The transaction was rolled back.
    Sqlite(rusqlite::Error),
    /// A stored value is not one the Python daemon writes.
    Corrupt {
        /// The column with the unknown value.
        column: &'static str,
    },
    /// No utterance or segment has this identity.
    NotFound,
    /// The lifecycle refuses the requested state change.
    Transition(InvalidTransition),
    /// The caller supplied a value the Python daemon would refuse.
    Invalid(&'static str),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sqlite(error) => write!(formatter, "sqlite: {error}"),
            Self::Corrupt { column } => write!(formatter, "unknown value in column {column}"),
            Self::NotFound => formatter.write_str("no such utterance"),
            Self::Transition(error) => error.fmt(formatter),
            Self::Invalid(reason) => formatter.write_str(reason),
        }
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Sqlite(error) => Some(error),
            Self::Transition(error) => Some(error),
            Self::Corrupt { .. } | Self::NotFound | Self::Invalid(_) => None,
        }
    }
}

impl From<rusqlite::Error> for Error {
    fn from(error: rusqlite::Error) -> Self {
        Self::Sqlite(error)
    }
}

impl From<InvalidTransition> for Error {
    fn from(error: InvalidTransition) -> Self {
        Self::Transition(error)
    }
}

/// The result of a store operation.
pub type Result<T> = core::result::Result<T, Error>;

/// One open connection to the state database.
pub struct Store {
    db: Connection,
    clock: Box<dyn Clock>,
}

impl fmt::Debug for Store {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.debug_struct("Store").finish_non_exhaustive()
    }
}

impl Store {
    /// Open, creating if needed, the database at `path` and apply missing migrations.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] when the file cannot be opened or migrated.
    pub fn open(path: &Path, clock: impl Clock + 'static) -> Result<Self> {
        let db = Connection::open(path)?;
        schema::migrate(&db)?;
        restrict_permissions(path);
        Ok(Self {
            db,
            clock: Box::new(clock),
        })
    }

    /// Wrap an already open connection, such as a fault-injecting test connection.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] when migration fails.
    pub fn from_connection(db: Connection, clock: impl Clock + 'static) -> Result<Self> {
        schema::migrate(&db)?;
        Ok(Self {
            db,
            clock: Box::new(clock),
        })
    }

    /// The input and playback queues, transitions, and restart recovery.
    pub fn queue(&self) -> queue::Queue<'_> {
        queue::Queue { store: self }
    }

    /// Terminal utterances.
    pub fn history(&self) -> history::History<'_> {
        history::History { store: self }
    }

    /// Persisted string settings.
    pub fn settings(&self) -> settings::Settings<'_> {
        settings::Settings { store: self }
    }

    /// Voice assignments per client source.
    pub fn voices(&self) -> voices::Voices<'_> {
        voices::Voices { store: self }
    }

    /// Close the connection so the Python daemon can reopen the file.
    ///
    /// # Errors
    /// Returns [`Error::Sqlite`] when SQLite refuses to close.
    pub fn close(self) -> Result<()> {
        self.db.close().map_err(|(_, error)| Error::Sqlite(error))
    }
}

/// Match the Python adapter: the database and its sidecars are private to the owner.
fn restrict_permissions(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        for suffix in ["", "-wal", "-shm", "-journal"] {
            let mut file = path.as_os_str().to_owned();
            file.push(suffix);
            // A missing sidecar is normal; nothing else here can fail usefully.
            let _ignored = std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600));
        }
    }
    #[cfg(not(unix))]
    let _ = path;
}

/// The text values the Python daemon stores for each enumeration.
pub mod names {
    use crate::{Priority, Sensitivity, State, codec};

    /// The stored lifecycle value, such as `Queued`.
    pub fn state(state: State) -> &'static str {
        codec::state_name(state)
    }

    /// The stored disclosure value, such as `confidential`.
    pub const fn sensitivity(sensitivity: Sensitivity) -> &'static str {
        codec::sensitivity_name(sensitivity)
    }

    /// The stored priority value, such as `normal`.
    pub const fn priority(priority: Priority) -> &'static str {
        codec::priority_name(priority)
    }
}
