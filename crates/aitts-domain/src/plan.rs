// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns stable queue order and decisions about nested preemption.
//! It does not suspend devices, persist positions, or start playback.

#![deny(clippy::arithmetic_side_effects)]

use crate::{CollectionLimit, utterance::State};
use alloc::vec::Vec;
use core::{cmp::Ordering, fmt};

/// A caller-supplied utterance identity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct UtteranceId<'a>(pub &'a str);

/// A finite queue key. Equal keys retain caller snapshot order.
#[derive(Clone, Copy, Debug, PartialEq, PartialOrd)]
pub struct OrderKey(f64);

/// An ordering key cannot represent a finite, distinct position.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InvalidOrderKey;
impl fmt::Display for InvalidOrderKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("queue key must be finite and preserve a distinct position")
    }
}
impl core::error::Error for InvalidOrderKey {}
impl OrderKey {
    /// Validate an observed finite key.
    ///
    /// # Errors
    /// Returns `InvalidOrderKey` for infinity or NaN.
    pub fn new(value: f64) -> Result<Self, InvalidOrderKey> {
        if value.is_finite() {
            Ok(Self(value))
        } else {
            Err(InvalidOrderKey)
        }
    }
    /// The value stored by the caller.
    pub const fn value(self) -> f64 {
        self.0
    }
}

/// Admission priority. Existing queue order is always determined by its key.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Priority {
    /// Append after all history, including completed entries.
    Normal,
    /// Insert before nonterminal entries, without interrupting a current speaker.
    Urgent,
    /// Insert at the head and interrupt once audio is ready.
    Preempt,
}

/// Whether an utterance may occupy the playback device.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Playback {
    /// Eligible for playback.
    Play,
    /// Generate audio without playback.
    SynthesizeOnly,
}

/// The queue fields required to plan ordering and interruptions.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Entry<'a> {
    /// Stable utterance identity.
    pub id: UtteranceId<'a>,
    /// Queue position assigned at admission or reorder.
    pub order: OrderKey,
    /// Requested priority.
    pub priority: Priority,
    /// Current lifecycle state.
    pub state: State,
    /// Device admission mode.
    pub playback: Playback,
}

/// Whether an external playback hold prevents interruptions.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Hold {
    /// Playback planning may proceed.
    Open,
    /// Keep current device ownership unchanged.
    Held,
}

/// Order by key, retaining original order for equal keys regardless of priority.
///
/// # Errors
/// Refuses snapshots larger than [`crate::MAX_COLLECTION_ENTRIES`] before copying.
pub fn ordered<'a>(entries: &[Entry<'a>]) -> Result<Vec<Entry<'a>>, CollectionLimit> {
    crate::allocation::admit(entries.len())?;
    let mut result = entries.to_vec();
    result.sort_by(|left, right| {
        left.order
            .partial_cmp(&right.order)
            .unwrap_or(Ordering::Equal)
    });
    Ok(result)
}

/// Allocate the same head or tail position as Python for representable keys.
///
/// # Errors
/// Returns `InvalidOrderKey` if floating point precision cannot create a distinct key.
pub fn admission_key(
    entries: &[Entry<'_>],
    priority: Priority,
) -> Result<OrderKey, InvalidOrderKey> {
    let (previous, next) = match priority {
        Priority::Normal => {
            let maximum = entries
                .iter()
                .map(|entry| entry.order.0)
                .reduce(f64::max)
                .unwrap_or(0.0);
            (maximum, maximum + 1.0)
        }
        Priority::Urgent | Priority::Preempt => {
            let minimum = entries
                .iter()
                .filter(|entry| !entry.state.is_terminal())
                .map(|entry| entry.order.0)
                .reduce(f64::min)
                .unwrap_or(1.0);
            (minimum, minimum - 1.0)
        }
    };
    if next.partial_cmp(&previous) == Some(Ordering::Equal) {
        return Err(InvalidOrderKey);
    }
    OrderKey::new(next)
}

/// Select the first ready preempting entry that precedes the current speaker.
/// A held queue, an equal key, an urgent request, or synthesis-only audio cannot interrupt.
pub fn preemption<'a>(
    entries: &[Entry<'a>],
    current: Option<Entry<'a>>,
    hold: Hold,
) -> Option<Entry<'a>> {
    if hold == Hold::Held {
        return None;
    }
    entries
        .iter()
        .copied()
        .filter(|entry| {
            entry.priority == Priority::Preempt
                && entry.state == State::Ready
                && entry.playback == Playback::Play
                && current.is_none_or(|current| {
                    current.state.is_terminal() || entry.order < current.order
                })
        })
        .fold(None, |best, entry| match best {
            Some(previous) if previous.order <= entry.order => Some(previous),
            _ => Some(entry),
        })
}

/// Index of a segment saved at interruption.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SegmentIndex(pub u32);

/// A saved interruption point. Device positions remain the caller's responsibility.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResumeFrame<'a> {
    /// Interrupted utterance.
    pub id: UtteranceId<'a>,
    /// Segment to resume, or an unsegmented clip.
    pub segment: Option<SegmentIndex>,
}

/// Pop the newest still-paused speaker, discarding missing or stale frames.
pub fn resume<'a>(
    stack: &mut Vec<ResumeFrame<'a>>,
    entries: &[Entry<'_>],
) -> Option<ResumeFrame<'a>> {
    while let Some(frame) = stack.pop() {
        if entries
            .iter()
            .any(|entry| entry.id == frame.id && entry.state == State::Paused)
        {
            return Some(frame);
        }
    }
    None
}
