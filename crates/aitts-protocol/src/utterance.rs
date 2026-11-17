// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Utterance projections used by queues, history, and current playback.

use crate::value::{Nullable, Number, Presence};
use crate::vocabulary::{Priority, Sensitivity, State};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// An utterance projection; optional fields identify richer history/current views.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Utterance {
    /// id.
    pub id: String,
    /// text.
    pub text: String,
    /// voice.
    pub voice: String,
    /// speed.
    pub speed: Number,
    /// sensitivity.
    pub sensitivity: Sensitivity,
    /// priority.
    pub priority: Priority,
    /// state.
    pub state: State,
    /// enqueued at.
    pub enqueued_at: Number,
    /// source.
    pub source: Nullable<String>,
    /// duration ms.
    pub duration_ms: Nullable<u64>,
    /// played ms.
    pub played_ms: Nullable<u64>,
    /// error.
    pub error: Nullable<String>,
    /// replay of.
    pub replay_of: Nullable<String>,
    /// playback.
    pub playback: bool,
    /// composite.
    pub composite: bool,
    /// segment count.
    pub segment_count: u64,
    /// completed segments.
    pub completed_segments: u64,
    /// final state.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub final_state: Presence<State>,
    /// finished at.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub finished_at: Presence<Number>,
    /// audio cached.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub audio_cached: Presence<bool>,
    /// segments.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub segments: Presence<Vec<SynthesizedSegment>>,
    /// position ms.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub position_ms: Presence<Nullable<u64>>,
    /// active segment.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub active_segment: Presence<ActiveSegment>,
}

/// A generated segment exposed to a synthesis-only client.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SynthesizedSegment {
    /// index.
    pub index: u64,
    /// state.
    pub state: State,
    /// duration ms.
    pub duration_ms: Nullable<u64>,
    /// audio ready.
    pub audio_ready: bool,
    /// audio path.
    pub audio_path: Nullable<String>,
    /// error.
    pub error: Nullable<String>,
}

/// The currently playing segment and its position.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ActiveSegment {
    /// index.
    pub index: u64,
    /// number.
    pub number: u64,
    /// count.
    pub count: u64,
    /// text.
    pub text: String,
    /// state.
    pub state: State,
    /// duration ms.
    pub duration_ms: Nullable<u64>,
    /// position ms.
    pub position_ms: Nullable<u64>,
}

crate::strict::object_only!(Utterance, SynthesizedSegment, ActiveSegment);
