// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Closed replies for queue, playback, voice, and settings controls.

use crate::catalog::Assignment;
use crate::settings::SettingsSnapshot;
use crate::value::{Nullable, Presence, Success};
use crate::vocabulary::{Priority, State};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// Result of a playback control operation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Transport {
    /// ok.
    pub ok: Success,
    /// state.
    pub state: Nullable<State>,
    /// current.
    pub current: Nullable<String>,
    /// held.
    pub held: bool,
}

/// Result of rewind, optionally creating a replay.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Rewound {
    /// ok.
    pub ok: Success,
    /// state.
    pub state: Nullable<State>,
    /// current.
    pub current: Nullable<String>,
    /// held.
    pub held: bool,
    /// replay id.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub replay_id: Presence<String>,
}

/// Result of moving between utterance segments.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SegmentStep {
    /// ok.
    pub ok: Success,
    /// state.
    pub state: Nullable<State>,
    /// current.
    pub current: Nullable<String>,
    /// held.
    pub held: bool,
    /// segment index.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub segment_index: Presence<u64>,
    /// segment number.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub segment_number: Presence<u64>,
}

/// A new utterance queued from history.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Requeued {
    /// ok.
    pub ok: Success,
    /// id.
    pub id: String,
    /// state.
    pub state: State,
    /// priority.
    pub priority: Priority,
    /// composite.
    pub composite: bool,
    /// segment count.
    pub segment_count: u64,
}

/// The resulting pending order.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Reordered {
    /// ok.
    pub ok: Success,
    /// ids.
    pub ids: Vec<String>,
}

/// The utterance state after cancellation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Cancelled {
    /// ok.
    pub ok: Success,
    /// id.
    pub id: String,
    /// state.
    pub state: State,
}

/// One explicit history removal.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct HistoryRemoved {
    /// ok.
    pub ok: Success,
    /// removed.
    pub removed: u64,
    /// id.
    pub id: String,
}

/// Number of items cleared.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Cleared {
    /// ok.
    pub ok: Success,
    /// cleared.
    pub cleared: u64,
}

/// Completed cache reclamation counts.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct CachePurged {
    /// ok.
    pub ok: Success,
    /// removed files.
    pub removed_files: u64,
    /// removed bytes.
    pub removed_bytes: u64,
    /// protected files.
    pub protected_files: u64,
    /// protected bytes.
    pub protected_bytes: u64,
    /// failed files.
    pub failed_files: u64,
    /// failed bytes.
    pub failed_bytes: u64,
}

/// The current engine's voices.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Voices {
    /// ok.
    pub ok: Success,
    /// voices.
    pub voices: Vec<String>,
}

/// Caller voice assignments.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct VoiceAssignments {
    /// ok.
    pub ok: Success,
    /// assignments.
    pub assignments: Vec<Assignment>,
}

/// The allocated assignment, or null after release.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct VoiceAssigned {
    /// ok.
    pub ok: Success,
    /// assignment.
    pub assignment: Nullable<Assignment>,
}

/// The full settings state after an optional update.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Settings {
    /// ok.
    pub ok: Success,
    /// settings.
    pub settings: SettingsSnapshot,
}

/// Transport acknowledgement before subscription events.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Subscribed {
    /// ok.
    pub ok: Success,
    /// subscribed.
    pub subscribed: Success,
}

crate::strict::object_only!(
    Transport,
    Rewound,
    SegmentStep,
    Requeued,
    Reordered,
    Cancelled,
    HistoryRemoved,
    Cleared,
    CachePurged,
    Voices,
    VoiceAssignments,
    VoiceAssigned,
    Settings,
    Subscribed
);
