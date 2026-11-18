// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns synthesis hand-off and device transfers.

use aitts_domain::plan::{self, Hold, Playback, ResumeFrame, UtteranceId};
use aitts_domain::utterance::State;

use super::{Conductor, Outcome, Refusal, Transfer};

impl Conductor {
    /// Take or release the hold, pausing or resuming the current speaker.
    pub(super) fn hold(&mut self, held: bool) -> Outcome {
        self.held = held;
        if let Some(id) = self.current.clone() {
            let (from, to) = if held {
                (State::Playing, State::Paused)
            } else {
                (State::Paused, State::Playing)
            };
            // A speaker already in the destination state is left as it is.
            let _unchanged = self.move_clip(&id, from, to);
        }
        Outcome::Applied
    }

    /// The sink finished, or failed, the current speaker.
    pub(super) fn finish(&mut self, id: &str, end: State) -> Result<Outcome, Refusal> {
        // A sink that finishes while a pause holds its speaker still ends that
        // speaker: the audio is over, and resuming must not replay it.
        let paused_current = self.current.as_deref() == Some(id)
            && self
                .clips
                .iter()
                .any(|clip| clip.id == id && clip.state == State::Paused);
        let from = if paused_current {
            State::Paused
        } else {
            State::Playing
        };
        let outcome = self.move_clip(id, from, end)?;
        if self.current.as_deref() == Some(id) {
            self.current = None;
        }
        Ok(outcome)
    }

    /// Interrupt for the first ready preempting clip ahead of the current speaker.
    pub(super) fn preempt(&mut self) -> Option<Transfer> {
        let entries = self.entries();
        let current = self
            .current
            .as_deref()
            .and_then(|id| entries.iter().copied().find(|entry| entry.id.0 == id));
        let started = plan::preemption(&entries, current, Hold::Open)?
            .id
            .0
            .to_owned();
        let suspended = self.current.take();
        if let Some(id) = &suspended {
            self.set_state(id, State::Paused);
            self.stack.push(id.clone());
        }
        self.set_state(&started, State::Playing);
        self.current = Some(started.clone());
        Some(Transfer::Preempt { suspended, started })
    }

    /// Return the newest still-paused preempted speaker to an idle device.
    pub(super) fn restore(&mut self) -> Option<Transfer> {
        if self.current.is_some() {
            return None;
        }
        let entries = self.entries();
        let mut frames: Vec<ResumeFrame<'_>> = self
            .stack
            .iter()
            .map(|id| ResumeFrame {
                id: UtteranceId(id),
                segment: None,
            })
            .collect();
        let restored = plan::resume(&mut frames, &entries).map(|frame| frame.id.0.to_owned());
        let remaining = frames.len();
        drop(entries);
        self.stack.truncate(remaining);
        let id = restored?;
        self.set_state(&id, State::Playing);
        self.current = Some(id.clone());
        Some(Transfer::Restore(id))
    }

    /// Start the first ready clip owed to the listener on an idle device.
    pub(super) fn start_next(&mut self) -> Option<Transfer> {
        if self.current.is_some() {
            return None;
        }
        let id = self
            .clips()
            .into_iter()
            .find(|clip| clip.state == State::Ready && clip.playback == Playback::Play)?
            .id;
        self.set_state(&id, State::Playing);
        self.current = Some(id.clone());
        Some(Transfer::Start(id))
    }
}
