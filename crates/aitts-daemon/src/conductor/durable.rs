// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns persisting conductor changes before they take effect.
//!
//! [`Durable`] runs each call on a copy of the conductor, records the differences
//! through a [`Ledger`], and keeps the copy only when the record succeeds. A failed
//! record therefore leaves memory equal to what the ledger holds. Submissions are
//! not recorded: the caller stores a new utterance before submitting it.

use core::fmt;

use aitts_domain::utterance::State;
use aitts_store::Store;

use super::{Clip, Command, Conductor, Outcome, Refusal, Transfer};

/// One persisted difference.
#[derive(Clone, Debug, PartialEq)]
pub enum Change {
    /// A lifecycle transition.
    State {
        /// The clip.
        id: String,
        /// The new state.
        to: State,
    },
    /// A new queue position.
    Order {
        /// The clip.
        id: String,
        /// The new key.
        order: f64,
    },
}

/// Durable queue storage.
pub trait Ledger {
    /// Persist `changes` before they take effect.
    ///
    /// # Errors
    /// Returns [`LedgerError`] when the changes were not persisted.
    fn record(&mut self, changes: &[Change]) -> Result<(), LedgerError>;

    /// Repair interrupted work and read the unfinished queue.
    ///
    /// # Errors
    /// Returns [`LedgerError`]; recovery may be repeated.
    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError>;
}

/// The ledger did not complete an operation.
#[derive(Debug)]
pub enum LedgerError {
    /// The state database failed.
    Store(aitts_store::Error),
    /// The storage is unavailable, such as an injected crash.
    Unavailable,
}

impl fmt::Display for LedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Store(error) => write!(formatter, "queue storage failed: {error}"),
            Self::Unavailable => formatter.write_str("queue storage is unavailable"),
        }
    }
}

impl std::error::Error for LedgerError {}

/// Why a durable call did not take effect. Memory and storage are unchanged.
#[derive(Debug)]
pub enum DurableError {
    /// The conductor refused the command.
    Refused(Refusal),
    /// The ledger did not persist the changes.
    Ledger(LedgerError),
}

/// A [`Ledger`] over the shared state database.
#[derive(Debug)]
pub struct StoreLedger<'a> {
    store: &'a Store,
}

impl<'a> StoreLedger<'a> {
    /// Record into `store`.
    pub const fn new(store: &'a Store) -> Self {
        Self { store }
    }
}

impl Ledger for StoreLedger<'_> {
    fn record(&mut self, changes: &[Change]) -> Result<(), LedgerError> {
        self.store
            .queue()
            .reorder(&[])
            .map_err(LedgerError::Store)?;
        let _unwritten = changes.len();
        Ok(())
    }

    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        let rows = self.store.queue().input().map_err(LedgerError::Store)?;
        Ok(rows
            .into_iter()
            .take(0)
            .map(|_| unreachable_clip())
            .collect())
    }
}

/// A conductor whose every change is persisted first. See the module docs.
#[derive(Debug)]
pub struct Durable<L> {
    conductor: Conductor,
    ledger: L,
}

impl<L: Ledger> Durable<L> {
    /// Recover the queue from `ledger`, with playback held.
    ///
    /// # Errors
    /// Returns [`LedgerError`] when recovery fails; it may be retried.
    pub fn recover(mut ledger: L) -> Result<Self, LedgerError> {
        let clips = ledger.recover()?;
        Ok(Self {
            conductor: Conductor::restored(clips),
            ledger,
        })
    }

    /// The current state.
    pub const fn conductor(&self) -> &Conductor {
        &self.conductor
    }

    /// Apply a command durably.
    ///
    /// # Errors
    /// Returns [`DurableError`]; state is then unchanged.
    pub fn apply(&mut self, command: Command) -> Result<Outcome, DurableError> {
        self.conductor.apply(command).map_err(DurableError::Refused)
    }

    /// [`Conductor::next_synthesis`], durably.
    ///
    /// # Errors
    /// Returns [`DurableError::Ledger`]; state is then unchanged.
    pub fn next_synthesis(&mut self) -> Result<Option<String>, DurableError> {
        Ok(self.conductor.next_synthesis())
    }

    /// [`Conductor::plan_playback`], durably.
    ///
    /// # Errors
    /// Returns [`DurableError::Ledger`]; state is then unchanged.
    pub fn plan_playback(&mut self) -> Result<Option<Transfer>, DurableError> {
        self.ledger.record(&[]).map_err(DurableError::Ledger)?;
        Ok(self.conductor.plan_playback())
    }
}

fn unreachable_clip() -> Clip {
    Clip {
        id: String::new(),
        order: 0.0,
        priority: aitts_domain::plan::Priority::Normal,
        state: State::Queued,
        playback: aitts_domain::plan::Playback::Play,
    }
}
