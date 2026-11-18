// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns persisting conductor changes before they take effect.
//!
//! [`Durable`] runs each call on a copy of the conductor, records the differences
//! through a [`Ledger`], and keeps the copy only when the record succeeds. A failed
//! record therefore leaves memory equal to what the ledger holds. Submissions are
//! not recorded: the caller stores a new utterance before submitting it.

use core::fmt;

use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;
use aitts_store::{Store, Utterance};

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
        let mut transitions = Vec::new();
        let mut keys = Vec::new();
        for change in changes {
            match change {
                Change::State { id, to } => transitions.push((id.clone(), *to)),
                Change::Order { id, order } => keys.push((id.clone(), *order)),
            }
        }
        // One transaction: a crash between rows leaves none of them written.
        self.store
            .queue()
            .save(&transitions, &keys)
            .map_err(LedgerError::Store)
    }

    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        let queue = self.store.queue();
        queue.recover().map_err(LedgerError::Store)?;
        let mut rows = queue.input().map_err(LedgerError::Store)?;
        rows.extend(queue.playback().map_err(LedgerError::Store)?);
        Ok(rows.into_iter().map(clip).collect())
    }
}

fn clip(row: Utterance) -> Clip {
    Clip {
        id: row.id,
        order: row.order_key,
        priority: match row.priority {
            aitts_store::Priority::Normal => Priority::Normal,
            aitts_store::Priority::Urgent => Priority::Urgent,
            aitts_store::Priority::Preempt => Priority::Preempt,
        },
        state: row.state,
        playback: if row.playback {
            Playback::Play
        } else {
            Playback::SynthesizeOnly
        },
    }
}

/// The differences from `before` to `after` for clips both contain.
fn changes(before: &Conductor, after: &Conductor) -> Vec<Change> {
    let mut found = Vec::new();
    for new in &after.clips {
        let Some(old) = before.clips.iter().find(|old| old.id == new.id) else {
            continue;
        };
        if old.state != new.state {
            found.push(Change::State {
                id: new.id.clone(),
                to: new.state,
            });
        }
        if old.order.total_cmp(&new.order).is_ne() {
            found.push(Change::Order {
                id: new.id.clone(),
                order: new.order,
            });
        }
    }
    found
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

    /// Run `call` on a copy, persist its changes, then keep the copy.
    fn commit<T>(
        &mut self,
        call: impl FnOnce(&mut Conductor) -> Result<T, Refusal>,
    ) -> Result<T, DurableError> {
        let mut next = self.conductor.clone();
        let value = call(&mut next).map_err(DurableError::Refused)?;
        let found = changes(&self.conductor, &next);
        if !found.is_empty() {
            self.ledger.record(&found).map_err(DurableError::Ledger)?;
        }
        self.conductor = next;
        Ok(value)
    }

    /// Apply a command durably.
    ///
    /// # Errors
    /// Returns [`DurableError`]; state is then unchanged.
    pub fn apply(&mut self, command: Command) -> Result<Outcome, DurableError> {
        self.commit(|conductor| conductor.apply(command))
    }

    /// [`Conductor::next_synthesis`], durably.
    ///
    /// # Errors
    /// Returns [`DurableError::Ledger`]; state is then unchanged.
    pub fn next_synthesis(&mut self) -> Result<Option<String>, DurableError> {
        self.commit(|conductor| Ok(conductor.next_synthesis()))
    }

    /// [`Conductor::plan_playback`], durably.
    ///
    /// # Errors
    /// Returns [`DurableError::Ledger`]; state is then unchanged.
    pub fn plan_playback(&mut self) -> Result<Option<Transfer>, DurableError> {
        self.commit(|conductor| Ok(conductor.plan_playback()))
    }
}
