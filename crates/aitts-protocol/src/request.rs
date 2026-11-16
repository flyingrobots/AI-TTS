// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Request shapes preserve supplied fields; daemon policy validates their values.

use crate::operation::Operation;
use crate::settings::SettingsUpdate;
use crate::value::{Nullable, Number, Presence, Success};
use crate::vocabulary::{ClearQueue, ContentFormat, Priority, Queue, Sensitivity};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// History accepts an integer and Python's legacy literal true (which means one).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum HistoryLimit {
    /// Requested item count; the application requires a positive value.
    Count(u64),
    /// Legacy Python boolean-as-integer input.
    LegacyTrue(Success),
}

/// One typed daemon operation, including transport-level subscription.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Request {
    /// The `submit` operation.
    Submit {
        /// Source text.
        text: String,
        /// Source interpretation.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        content_format: Presence<ContentFormat>,
        /// Explicit voice selection.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        voice: Presence<Nullable<String>>,
        /// Explicit engine selection.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        engine: Presence<Nullable<String>>,
        /// Generation speed.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        speed: Presence<Nullable<Number>>,
        /// Disclosure policy.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        sensitivity: Presence<Sensitivity>,
        /// Queue admission priority.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        priority: Presence<Priority>,
        /// Legacy preemption request.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        preempt: Presence<bool>,
        /// Whether the daemon plays generated audio.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        playback: Presence<bool>,
        /// Caller identity.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        source: Presence<Nullable<String>>,
        /// Caller provenance.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        origin: Presence<Nullable<String>>,
    },
    /// The `engines` operation.
    Engines {},
    /// The `model_setup` operation.
    ModelSetup {
        /// Model catalog name.
        name: String,
        /// Require code-only refresh; daemon admission must refuse a full repair.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        refresh_only: Presence<bool>,
    },
    /// The `cancel_model_setup` operation.
    CancelModelSetup {},
    /// The `get` operation.
    Get {
        /// Utterance identifier.
        id: String,
    },
    /// The `list` operation.
    List {
        /// Queue to inspect.
        queue: Queue,
    },
    /// The `history` operation.
    History {
        /// Maximum returned items.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        limit: Presence<HistoryLimit>,
        /// Exclusive history cursor.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        before: Presence<Nullable<String>>,
    },
    /// The `export_evidence` operation.
    ExportEvidence {
        /// Utterance identifier.
        id: String,
        /// Requested export directory.
        destination: String,
    },
    /// The `provenance` operation.
    Provenance {
        /// Utterance identifier.
        id: String,
    },
    /// The `restart_model` operation.
    RestartModel {
        /// Engine to restart.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        engine: Presence<String>,
    },
    /// The `storage` operation.
    Storage {
        /// Requested retention policy.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        retention_days: Presence<Nullable<u64>>,
        /// Explicit deletion identifiers.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        delete: Presence<Nullable<Vec<String>>>,
    },
    /// The `pause` operation.
    Pause {
        /// Control origin.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        origin: Presence<Nullable<String>>,
    },
    /// The `resume` operation.
    Resume {
        /// Control origin.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        origin: Presence<Nullable<String>>,
    },
    /// The `resume_when_input_idle` operation.
    ResumeWhenInputIdle {},
    /// The `skip` operation.
    Skip {},
    /// The `rewind` operation.
    Rewind {
        /// Explicit replay target.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        to: Presence<Nullable<String>>,
    },
    /// The `next_segment` operation.
    NextSegment {},
    /// The `previous_segment` operation.
    PreviousSegment {},
    /// The `requeue` operation.
    Requeue {
        /// Utterance identifier.
        id: String,
        /// New queue priority.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        priority: Presence<Priority>,
    },
    /// The `reorder` operation.
    Reorder {
        /// Desired pending order.
        ids: Vec<String>,
    },
    /// The `cancel` operation.
    Cancel {
        /// Utterance identifier.
        id: String,
    },
    /// The `remove_history` operation.
    RemoveHistory {
        /// History identifier.
        id: String,
    },
    /// The `clear` operation.
    Clear {
        /// Collection to clear.
        queue: ClearQueue,
        /// Whether to delete cached history audio.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        delete_files: Presence<bool>,
    },
    /// The `purge_cache` operation.
    PurgeCache {},
    /// The `status` operation.
    Status {},
    /// The `metrics` operation.
    Metrics {},
    /// The `snapshot` operation.
    Snapshot {
        /// Maximum history items.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        limit: Presence<HistoryLimit>,
    },
    /// The `voices` operation.
    Voices {},
    /// The `voice_assignments` operation.
    VoiceAssignments {},
    /// The `assign_voice` operation.
    AssignVoice {
        /// Caller identity.
        source: String,
        /// Voice to assign.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        voice: Presence<Nullable<String>>,
        /// Release an assignment.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        release: Presence<bool>,
    },
    /// The `settings` operation.
    Settings {
        /// Optional settings update.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        set: Presence<Nullable<SettingsUpdate>>,
    },
    /// The `subscribe` operation.
    Subscribe {
        /// Opt in to playback progress events.
        #[serde(default, skip_serializing_if = "Presence::is_absent")]
        playback_progress: Presence<bool>,
    },
}

impl Request {
    /// Return the operation needed to decode this request's untagged reply.
    pub const fn operation(&self) -> Operation {
        match self {
            Self::Submit { .. } => Operation::Submit,
            Self::Engines { .. } => Operation::Engines,
            Self::ModelSetup { .. } => Operation::ModelSetup,
            Self::CancelModelSetup { .. } => Operation::CancelModelSetup,
            Self::Get { .. } => Operation::Get,
            Self::List { .. } => Operation::List,
            Self::History { .. } => Operation::History,
            Self::ExportEvidence { .. } => Operation::ExportEvidence,
            Self::Provenance { .. } => Operation::Provenance,
            Self::RestartModel { .. } => Operation::RestartModel,
            Self::Storage { .. } => Operation::Storage,
            Self::Pause { .. } => Operation::Pause,
            Self::Resume { .. } => Operation::Resume,
            Self::ResumeWhenInputIdle { .. } => Operation::ResumeWhenInputIdle,
            Self::Skip { .. } => Operation::Skip,
            Self::Rewind { .. } => Operation::Rewind,
            Self::NextSegment { .. } => Operation::NextSegment,
            Self::PreviousSegment { .. } => Operation::PreviousSegment,
            Self::Requeue { .. } => Operation::Requeue,
            Self::Reorder { .. } => Operation::Reorder,
            Self::Cancel { .. } => Operation::Cancel,
            Self::RemoveHistory { .. } => Operation::RemoveHistory,
            Self::Clear { .. } => Operation::Clear,
            Self::PurgeCache { .. } => Operation::PurgeCache,
            Self::Status { .. } => Operation::Status,
            Self::Metrics { .. } => Operation::Metrics,
            Self::Snapshot { .. } => Operation::Snapshot,
            Self::Voices { .. } => Operation::Voices,
            Self::VoiceAssignments { .. } => Operation::VoiceAssignments,
            Self::AssignVoice { .. } => Operation::AssignVoice,
            Self::Settings { .. } => Operation::Settings,
            Self::Subscribe { .. } => Operation::Subscribe,
        }
    }
}
