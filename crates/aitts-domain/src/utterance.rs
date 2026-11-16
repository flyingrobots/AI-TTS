// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns utterance lifecycle states and their legal transitions.

use core::fmt;

/// Every state in the Python model's closed lifecycle.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum State {
    /// Accepted, before queue placement.
    Submitted,
    /// Waiting for synthesis.
    Queued,
    /// Synthesis owns the work.
    Synthesizing,
    /// Audio is ready to play.
    Ready,
    /// Audio owns the playback device.
    Playing,
    /// Playback retains a resumable position.
    Paused,
    /// Playback completed.
    Played,
    /// The listener skipped playback.
    Skipped,
    /// Work was cancelled before playback.
    Cancelled,
    /// Synthesis or playback failed.
    Failed,
}

impl State {
    /// Whether the state has no outgoing transition.
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Played | Self::Skipped | Self::Cancelled | Self::Failed
        )
    }

    /// Move to the requested state without mutating a rejected source state.
    ///
    /// # Errors
    /// Returns both states when the Python lifecycle refuses the transition.
    pub const fn transition(self, destination: Self) -> Result<Self, InvalidTransition> {
        let permitted = match self {
            Self::Submitted => matches!(destination, Self::Queued),
            Self::Queued => matches!(destination, Self::Synthesizing | Self::Cancelled),
            Self::Synthesizing => matches!(
                destination,
                Self::Ready | Self::Failed | Self::Cancelled | Self::Queued
            ),
            Self::Ready => matches!(destination, Self::Playing | Self::Cancelled | Self::Failed),
            Self::Playing | Self::Paused => matches!(
                (self, destination),
                (Self::Playing, Self::Paused)
                    | (Self::Paused, Self::Playing)
                    | (_, Self::Played | Self::Skipped | Self::Failed)
            ),
            Self::Played | Self::Skipped | Self::Cancelled | Self::Failed => false,
        };
        if permitted {
            Ok(destination)
        } else {
            Err(InvalidTransition {
                source: self,
                destination,
            })
        }
    }
}

/// A refused state change. The current state remains valid and unchanged.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InvalidTransition {
    /// The state from which the transition was requested.
    pub source: State,
    /// The disallowed destination.
    pub destination: State,
}

impl fmt::Display for InvalidTransition {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "transition from {:?} to {:?} is not permitted",
            self.source, self.destination
        )
    }
}

impl core::error::Error for InvalidTransition {}
