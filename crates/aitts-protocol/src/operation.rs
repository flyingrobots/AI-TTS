// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Operation identity supplies context for untagged daemon replies.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// Operation identity; subscription belongs to the socket transport.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Operation {
    /// The `submit` operation.
    Submit,
    /// The `engines` operation.
    Engines,
    /// The `model_setup` operation.
    ModelSetup,
    /// The `cancel_model_setup` operation.
    CancelModelSetup,
    /// The `get` operation.
    Get,
    /// The `list` operation.
    List,
    /// The `history` operation.
    History,
    /// The `export_evidence` operation.
    ExportEvidence,
    /// The `provenance` operation.
    Provenance,
    /// The `restart_model` operation.
    RestartModel,
    /// The `storage` operation.
    Storage,
    /// The `pause` operation.
    Pause,
    /// The `resume` operation.
    Resume,
    /// The `resume_when_input_idle` operation.
    ResumeWhenInputIdle,
    /// The `skip` operation.
    Skip,
    /// The `rewind` operation.
    Rewind,
    /// The `next_segment` operation.
    NextSegment,
    /// The `previous_segment` operation.
    PreviousSegment,
    /// The `requeue` operation.
    Requeue,
    /// The `reorder` operation.
    Reorder,
    /// The `cancel` operation.
    Cancel,
    /// The `remove_history` operation.
    RemoveHistory,
    /// The `clear` operation.
    Clear,
    /// The `purge_cache` operation.
    PurgeCache,
    /// The `status` operation.
    Status,
    /// The `metrics` operation.
    Metrics,
    /// The `snapshot` operation.
    Snapshot,
    /// The `voices` operation.
    Voices,
    /// The `voice_assignments` operation.
    VoiceAssignments,
    /// The `assign_voice` operation.
    AssignVoice,
    /// The `settings` operation.
    Settings,
    /// The `subscribe` operation.
    Subscribe,
}

impl Operation {
    /// All supported operations in dispatcher order, then subscription.
    pub const ALL: [Self; 32] = [
        Self::Submit,
        Self::Engines,
        Self::ModelSetup,
        Self::CancelModelSetup,
        Self::Get,
        Self::List,
        Self::History,
        Self::ExportEvidence,
        Self::Provenance,
        Self::RestartModel,
        Self::Storage,
        Self::Pause,
        Self::Resume,
        Self::ResumeWhenInputIdle,
        Self::Skip,
        Self::Rewind,
        Self::NextSegment,
        Self::PreviousSegment,
        Self::Requeue,
        Self::Reorder,
        Self::Cancel,
        Self::RemoveHistory,
        Self::Clear,
        Self::PurgeCache,
        Self::Status,
        Self::Metrics,
        Self::Snapshot,
        Self::Voices,
        Self::VoiceAssignments,
        Self::AssignVoice,
        Self::Settings,
        Self::Subscribe,
    ];

    /// The operation's JSON tag.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Submit => "submit",
            Self::Engines => "engines",
            Self::ModelSetup => "model_setup",
            Self::CancelModelSetup => "cancel_model_setup",
            Self::Get => "get",
            Self::List => "list",
            Self::History => "history",
            Self::ExportEvidence => "export_evidence",
            Self::Provenance => "provenance",
            Self::RestartModel => "restart_model",
            Self::Storage => "storage",
            Self::Pause => "pause",
            Self::Resume => "resume",
            Self::ResumeWhenInputIdle => "resume_when_input_idle",
            Self::Skip => "skip",
            Self::Rewind => "rewind",
            Self::NextSegment => "next_segment",
            Self::PreviousSegment => "previous_segment",
            Self::Requeue => "requeue",
            Self::Reorder => "reorder",
            Self::Cancel => "cancel",
            Self::RemoveHistory => "remove_history",
            Self::Clear => "clear",
            Self::PurgeCache => "purge_cache",
            Self::Status => "status",
            Self::Metrics => "metrics",
            Self::Snapshot => "snapshot",
            Self::Voices => "voices",
            Self::VoiceAssignments => "voice_assignments",
            Self::AssignVoice => "assign_voice",
            Self::Settings => "settings",
            Self::Subscribe => "subscribe",
        }
    }
}
