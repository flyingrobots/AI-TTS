// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the commands that change queue membership and order.

use std::collections::BTreeSet;

use aitts_domain::plan::{self, Entry, OrderKey, Playback, Priority, UtteranceId};
use aitts_domain::utterance::State;

use super::{Clip, Conductor, Outcome, Refusal};

/// Work still owed after the current speaker, as Python `_PENDING_STATES`.
const PENDING: [State; 3] = [State::Queued, State::Synthesizing, State::Ready];

impl Conductor {
    pub(super) fn entries(&self) -> Vec<Entry<'_>> {
        self.clips
            .iter()
            .filter_map(|clip| {
                Some(Entry {
                    id: UtteranceId(&clip.id),
                    order: OrderKey::new(clip.order).ok()?,
                    priority: clip.priority,
                    state: clip.state,
                    playback: clip.playback,
                })
            })
            .collect()
    }

    pub(super) fn submit(
        &mut self,
        id: String,
        priority: Priority,
        playback: Playback,
    ) -> Result<Outcome, Refusal> {
        if self.index(&id).is_ok() {
            return Err(Refusal::Duplicate(id));
        }
        let order = plan::admission_key(&self.entries(), priority)
            .map_err(|_| Refusal::OrderExhausted)?
            .value();
        self.clips.push(Clip {
            id,
            order,
            priority,
            state: State::Queued,
            playback,
        });
        Ok(Outcome::Applied)
    }

    /// Admit a clip at the order key the store assigned.
    pub(super) fn admit(
        &mut self,
        id: String,
        order: f64,
        priority: Priority,
        playback: Playback,
    ) -> Result<Outcome, Refusal> {
        if self.index(&id).is_ok() {
            return Err(Refusal::Duplicate(id));
        }
        let order = OrderKey::new(order)
            .map_err(|_| Refusal::OrderExhausted)?
            .value();
        self.clips.push(Clip {
            id,
            order,
            priority,
            state: State::Queued,
            playback,
        });
        Ok(Outcome::Applied)
    }

    /// Admit a replay of a finished clip, as Python `_op_requeue`.
    pub(super) fn requeue(
        &mut self,
        source: &str,
        id: String,
        priority: Priority,
    ) -> Result<Outcome, Refusal> {
        let original = self
            .clips
            .get(self.index(source)?)
            .map(|clip| (clip.state, clip.playback));
        match original {
            Some((state, playback)) if state.is_terminal() => self.submit(id, priority, playback),
            Some((state, _)) => Err(Refusal::IllegalState {
                id: source.to_owned(),
                state,
            }),
            None => Err(Refusal::NotFound(source.to_owned())),
        }
    }

    /// Cancel work that has not reached the device, as Python `_op_cancel`.
    pub(super) fn cancel(&mut self, id: &str) -> Result<Outcome, Refusal> {
        let state = self.clips.get(self.index(id)?).map(|clip| clip.state);
        match state {
            Some(from @ (State::Queued | State::Synthesizing | State::Ready)) => {
                self.move_clip(id, from, State::Cancelled)
            }
            Some(state) => Err(Refusal::IllegalState {
                id: id.to_owned(),
                state,
            }),
            None => Err(Refusal::NotFound(id.to_owned())),
        }
    }

    /// Skip preempted speakers, then cancel pending work; the current speaker stays.
    pub(super) fn clear(&mut self) -> usize {
        let mut cleared = 0_usize;
        while let Some(id) = self.stack.pop() {
            if self.move_clip(&id, State::Paused, State::Skipped).is_ok() {
                cleared = cleared.saturating_add(1);
            }
        }
        for clip in &mut self.clips {
            if PENDING.contains(&clip.state) {
                clip.state = State::Cancelled;
                cleared = cleared.saturating_add(1);
            }
        }
        cleared
    }

    /// Replace pending order with an exact permutation, after the current speaker.
    pub(super) fn reorder(&mut self, ids: &[String]) -> Result<Outcome, Refusal> {
        let pending: BTreeSet<&str> = self
            .clips
            .iter()
            .filter(|clip| PENDING.contains(&clip.state) && clip.playback == Playback::Play)
            .map(|clip| clip.id.as_str())
            .collect();
        let named: BTreeSet<&str> = ids.iter().map(String::as_str).collect();
        if named.len() != ids.len() || named != pending {
            return Err(Refusal::NotPermutation);
        }
        let base = self
            .clips
            .iter()
            .filter(|clip| matches!(clip.state, State::Playing | State::Paused))
            .map(|clip| clip.order)
            .reduce(f64::max)
            .unwrap_or(0.0);
        let mut order = base;
        for id in ids {
            order += 1.0;
            if let Some(clip) = self.clips.iter_mut().find(|clip| clip.id == *id) {
                clip.order = order;
            }
        }
        Ok(Outcome::Applied)
    }

    /// Mark audio ready, or report it unowed when the clip left synthesis.
    pub(super) fn audio_ready(&mut self, id: &str) -> Result<Outcome, Refusal> {
        let state = self.clips.get(self.index(id)?).map(|clip| clip.state);
        if state.is_some_and(State::is_terminal) {
            return Ok(Outcome::Discarded);
        }
        self.move_clip(id, State::Synthesizing, State::Ready)
    }
}
