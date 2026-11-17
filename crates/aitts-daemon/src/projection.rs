// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the wire projection of stored utterances.
//!
//! It follows the Python daemon's `_serialize` and `_serialize_utterance`: base
//! fields, composite counts, segment readiness for synthesis-only work, and the
//! history fields for terminal work.

use std::path::Path;

use aitts_protocol::utterance::{SynthesizedSegment, Utterance as WireUtterance};
use aitts_protocol::value::{Nullable, Number, Presence};
use aitts_protocol::vocabulary::{Priority, Sensitivity, State};
use aitts_store::{Segment, Utterance};

/// Which fields a projection carries.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum View {
    /// Queue fields only.
    Queue,
    /// Queue fields plus final state, finish time, and cache presence.
    History,
}

/// Project `utterance` and its `segments` for the wire.
pub(crate) fn utterance(utterance: &Utterance, segments: &[Segment], view: View) -> WireUtterance {
    let completed = segments
        .iter()
        .filter(|segment| {
            matches!(
                segment.state,
                aitts_store::State::Played | aitts_store::State::Skipped
            )
        })
        .count();
    let mut item = WireUtterance {
        id: utterance.id.clone(),
        text: utterance.text.clone(),
        voice: utterance.voice.clone(),
        speed: number(utterance.speed),
        sensitivity: sensitivity(utterance.sensitivity),
        priority: priority(utterance.priority),
        state: state(utterance.state),
        enqueued_at: number(utterance.submitted_at),
        source: nullable(utterance.source.clone()),
        duration_ms: milliseconds(utterance.duration_ms),
        played_ms: milliseconds(utterance.played_ms),
        error: nullable(utterance.error.clone()),
        replay_of: nullable(utterance.replay_of.clone()),
        playback: utterance.playback,
        composite: !segments.is_empty(),
        segment_count: count(segments.len().max(1)),
        completed_segments: count(completed),
        final_state: Presence::Absent,
        finished_at: Presence::Absent,
        audio_cached: Presence::Absent,
        segments: Presence::Absent,
        position_ms: Presence::Absent,
        active_segment: Presence::Absent,
    };
    if !utterance.playback {
        item.segments = Presence::Present(synthesized(utterance, segments));
    }
    if view == View::History {
        item.final_state = Presence::Present(state(utterance.state));
        item.finished_at = Presence::Present(number(utterance.state_changed_at));
        item.audio_cached = Presence::Present(if segments.is_empty() {
            exists(utterance.audio_path.as_deref())
        } else {
            segments
                .iter()
                .all(|segment| exists(segment.audio_path.as_deref()))
        });
    }
    item
}

fn synthesized(utterance: &Utterance, segments: &[Segment]) -> Vec<SynthesizedSegment> {
    if segments.is_empty() {
        return vec![SynthesizedSegment {
            index: 0,
            state: state(utterance.state),
            duration_ms: milliseconds(utterance.duration_ms),
            audio_ready: exists(utterance.audio_path.as_deref()),
            audio_path: nullable(utterance.audio_path.clone()),
            error: nullable(utterance.error.clone()),
        }];
    }
    segments
        .iter()
        .map(|segment| SynthesizedSegment {
            index: u64::try_from(segment.index).unwrap_or_default(),
            state: state(segment.state),
            duration_ms: milliseconds(segment.duration_ms),
            audio_ready: exists(segment.audio_path.as_deref()),
            audio_path: nullable(segment.audio_path.clone()),
            error: nullable(segment.error.clone()),
        })
        .collect()
}

fn exists(path: Option<&str>) -> bool {
    path.is_some_and(|path| Path::new(path).exists())
}

/// A stored float as a JSON number; a non-finite value, which SQLite cannot hold, is zero.
pub(crate) fn number(value: f64) -> Number {
    Number::from_f64(value).unwrap_or_else(|| Number::from(0_u8))
}

fn milliseconds(value: Option<i64>) -> Nullable<u64> {
    value
        .and_then(|value| u64::try_from(value).ok())
        .map_or(Nullable::Null, Nullable::Value)
}

fn nullable(value: Option<String>) -> Nullable<String> {
    value.map_or(Nullable::Null, Nullable::Value)
}

/// A collection length as a wire count.
pub(crate) fn count(length: usize) -> u64 {
    u64::try_from(length).unwrap_or(u64::MAX)
}

/// The wire spelling of a stored lifecycle state.
pub(crate) const fn state(state: aitts_store::State) -> State {
    use aitts_store::State as Stored;
    match state {
        Stored::Submitted => State::Submitted,
        Stored::Queued => State::Queued,
        Stored::Synthesizing => State::Synthesizing,
        Stored::Ready => State::Ready,
        Stored::Playing => State::Playing,
        Stored::Paused => State::Paused,
        Stored::Played => State::Played,
        Stored::Skipped => State::Skipped,
        Stored::Cancelled => State::Cancelled,
        Stored::Failed => State::Failed,
    }
}

const fn sensitivity(sensitivity: aitts_store::Sensitivity) -> Sensitivity {
    match sensitivity {
        aitts_store::Sensitivity::Public => Sensitivity::Public,
        aitts_store::Sensitivity::Internal => Sensitivity::Internal,
        aitts_store::Sensitivity::Confidential => Sensitivity::Confidential,
    }
}

const fn priority(priority: aitts_store::Priority) -> Priority {
    match priority {
        aitts_store::Priority::Normal => Priority::Normal,
        aitts_store::Priority::Urgent => Priority::Urgent,
        aitts_store::Priority::Preempt => Priority::Preempt,
    }
}
