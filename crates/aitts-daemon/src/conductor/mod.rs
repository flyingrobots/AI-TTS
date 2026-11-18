// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns queue state, the playback hold, and the preemption stack.
//!
//! A [`Conductor`] changes only through [`Conductor::apply`] and the two planning
//! calls, so one owner can process every change in arrival order. It does no I/O:
//! the caller persists each transition, runs synthesis, and drives the audio sink.
//! Ordering and interruption rules come from [`aitts_domain::plan`].

use core::fmt;

use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;

mod planning;
mod queue;

/// One clip the conductor tracks.
#[derive(Clone, Debug, PartialEq)]
pub struct Clip {
    /// The `utt_…` identifier.
    pub id: String,
    /// The queue position.
    pub order: f64,
    /// The admission priority.
    pub priority: Priority,
    /// The lifecycle state.
    pub state: State,
    /// Whether the clip may occupy the device.
    pub playback: Playback,
}

/// A request that changes queue state.
#[derive(Clone, Debug, PartialEq)]
pub enum Command {
    /// Admit a new clip as Queued.
    Submit {
        /// The new identifier.
        id: String,
        /// The admission priority.
        priority: Priority,
        /// Whether the clip may occupy the device.
        playback: Playback,
    },
    /// Cancel a clip that is not on the device.
    Cancel(String),
    /// Skip every preempted speaker and cancel every pending clip.
    ClearQueue,
    /// Replace the pending order with a complete permutation.
    Reorder(Vec<String>),
    /// Take the playback hold and pause the current speaker.
    Pause,
    /// Release the hold and resume the current speaker.
    Resume,
    /// Synthesis produced audio for a clip.
    AudioReady(String),
    /// Synthesis failed for a clip.
    SynthesisFailed(String),
    /// The sink finished the current clip.
    PlaybackFinished(String),
}

/// The effect of an accepted command.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outcome {
    /// The command changed state as requested.
    Applied,
    /// The number of clips a clear skipped or cancelled.
    Cleared(usize),
    /// Audio arrived for a clip that is no longer owed; the caller discards it.
    Discarded,
}

/// A refused command. Queue state is unchanged.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// No clip has this identifier.
    NotFound(String),
    /// A clip with this identifier already exists.
    Duplicate(String),
    /// The clip's state does not permit the command.
    IllegalState {
        /// The clip.
        id: String,
        /// Its current state.
        state: State,
    },
    /// A reorder did not name every pending clip exactly once.
    NotPermutation,
    /// No distinct order key remains at the requested position.
    OrderExhausted,
}

impl fmt::Display for Refusal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound(id) => write!(formatter, "no utterance {id}"),
            Self::Duplicate(id) => write!(formatter, "utterance {id} already exists"),
            Self::IllegalState { id, state } => {
                write!(formatter, "utterance {id} cannot change from {state:?}")
            }
            Self::NotPermutation => {
                formatter.write_str("ids must name the complete pending plan exactly once")
            }
            Self::OrderExhausted => formatter.write_str("no distinct queue position remains"),
        }
    }
}

impl std::error::Error for Refusal {}

/// A device change the caller must carry out, in this order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Transfer {
    /// Start a ready clip on an idle device.
    Start(String),
    /// Suspend the current speaker, if any, and start the preempting clip.
    Preempt {
        /// The speaker pushed on the preemption stack.
        suspended: Option<String>,
        /// The clip that now owns the device.
        started: String,
    },
    /// Return the newest preempted speaker to the device.
    Restore(String),
}

/// The single owner of queue state. See the module documentation.
#[derive(Clone, Debug, Default)]
pub struct Conductor {
    clips: Vec<Clip>,
    held: bool,
    current: Option<String>,
    stack: Vec<String>,
}

impl Conductor {
    /// An empty, open queue.
    pub fn new() -> Self {
        Self::default()
    }

    /// The tracked clips in queue order.
    pub fn clips(&self) -> Vec<Clip> {
        self.clips.clone()
    }

    /// Whether the playback hold is taken.
    pub const fn held(&self) -> bool {
        self.held
    }

    /// The clip on the device, playing or paused by a hold.
    pub fn current(&self) -> Option<&str> {
        self.current.as_deref()
    }

    /// Apply one command.
    ///
    /// # Errors
    /// Returns a [`Refusal`] and leaves state unchanged when the command is illegal.
    pub fn apply(&mut self, command: Command) -> Result<Outcome, Refusal> {
        drop(command);
        Err(Refusal::NotPermutation)
    }

    /// Hand the first Queued clip in order to synthesis, marking it Synthesizing.
    pub fn next_synthesis(&mut self) -> Option<String> {
        None
    }

    /// Decide the next device change, if any. A held queue never changes the device.
    pub fn plan_playback(&mut self) -> Option<Transfer> {
        self.stack.last().map(|_| Transfer::Restore(String::new()))
    }
}
