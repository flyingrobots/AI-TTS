// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Subscription events, including their closed discriminators and payloads.

use crate::catalog::Assignment;
use crate::codec::{MAX_RESPONSE_BYTES, WireError, decode, encode};
use crate::settings::SettingsUpdate;
use crate::status::{InputIdle, ListenerSpeaking};
use crate::value::{Nullable, Number};
use crate::vocabulary::State;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// One event sent after subscribing.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
pub enum Event {
    /// The `state_changed` event.
    StateChanged {
        /// id.
        id: String,
        /// from.
        from: Nullable<State>,
        /// to.
        to: State,
        /// at.
        at: Number,
    },
    /// The `segment_state_changed` event.
    SegmentStateChanged {
        /// id.
        id: String,
        /// segment index.
        segment_index: u64,
        /// from.
        from: State,
        /// to.
        to: State,
    },
    /// The `playback_progress` event.
    PlaybackProgress {
        /// playback held.
        playback_held: bool,
        /// id.
        id: Nullable<String>,
        /// position ms.
        position_ms: Nullable<u64>,
        /// audio peak.
        audio_peak: Nullable<Number>,
    },
    /// The `model_readiness_changed` event.
    ModelReadinessChanged {},
    /// The `model_setup_changed` event.
    ModelSetupChanged {},
    /// The `plan_reordered` event.
    PlanReordered {
        /// ids.
        ids: Vec<String>,
    },
    /// The `history_changed` event.
    HistoryChanged(HistoryChange),
    /// The `cache_changed` event.
    CacheChanged {
        /// removed files.
        removed_files: u64,
        /// removed bytes.
        removed_bytes: u64,
        /// protected files.
        protected_files: u64,
        /// protected bytes.
        protected_bytes: u64,
        /// failed files.
        failed_files: u64,
        /// failed bytes.
        failed_bytes: u64,
    },
    /// The `settings_changed` event.
    SettingsChanged {
        /// settings.
        settings: SettingsUpdate,
    },
    /// The `voice_assigned` event.
    VoiceAssigned {
        /// assignment.
        assignment: Assignment,
    },
    /// The `voice_released` event.
    VoiceReleased {
        /// source.
        source: String,
    },
    /// The `playback_interrupted` event.
    PlaybackInterrupted {
        /// reason.
        reason: ListenerSpeaking,
        /// resume armed.
        resume_armed: bool,
    },
    /// The `playback_resumed` event.
    PlaybackResumed {
        /// reason.
        reason: InputIdle,
    },
}

/// Exactly one kind of history edit.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum HistoryChange {
    /// A whole history clear.
    Cleared(HistoryCleared),
    /// One removed item.
    Removed(HistoryRemoved),
}

/// Number of items cleared from history.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct HistoryCleared {
    /// cleared.
    pub cleared: u64,
}

/// The removed history identifier.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct HistoryRemoved {
    /// removed.
    pub removed: String,
}

/// Parse a bounded event, rejecting unknown fields and invalid value kinds.
///
/// # Errors
/// Returns a typed framing or contract refusal.
pub fn decode_event(line: &[u8]) -> Result<Event, WireError> {
    decode(line)
}

/// Encode an event with a single newline within the response budget.
///
/// # Errors
/// Refuses an oversized serialized event.
pub fn encode_event(event: &Event) -> Result<Vec<u8>, WireError> {
    encode(event, MAX_RESPONSE_BYTES)
}
