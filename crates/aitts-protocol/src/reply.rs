// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Reply decoding uses the originating operation because replies carry no op tag.

use crate::codec::{MAX_RESPONSE_BYTES, WireError, decode, encode};
use crate::error_reply::ErrorReply;
use crate::operation::Operation;
use crate::{control_reply, metrics, query_reply, snapshot, status};
use schemars::JsonSchema;
use serde::Serialize;

/// A typed reply associated with the operation which produced it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, JsonSchema)]
#[serde(untagged)]
pub enum Reply {
    /// Any operation can report a structured daemon error.
    Error(ErrorReply),
    /// Result of `submit`.
    Submit(query_reply::Submitted),
    /// Result of `engines`.
    Engines(query_reply::Engines),
    /// Result of `model_setup`.
    ModelSetup(query_reply::ModelSetup),
    /// Result of `cancel_model_setup`.
    CancelModelSetup(query_reply::Acknowledged),
    /// Result of `get`.
    Get(query_reply::Item),
    /// Result of `list`.
    List(query_reply::Items),
    /// Result of `history`.
    History(query_reply::Items),
    /// Result of `export_evidence`.
    ExportEvidence(query_reply::Exported),
    /// Result of `provenance`, including bounded historical extensions.
    Provenance(crate::provenance::ProvenanceReply),
    /// Result of `restart_model`.
    RestartModel(query_reply::Acknowledged),
    /// Result of `storage`.
    Storage(query_reply::Storage),
    /// Result of `pause`.
    Pause(control_reply::Transport),
    /// Result of `resume`.
    Resume(control_reply::Transport),
    /// Result of `resume_when_input_idle`.
    ResumeWhenInputIdle(control_reply::Transport),
    /// Result of `skip`.
    Skip(control_reply::Transport),
    /// Result of `rewind`.
    Rewind(control_reply::Rewound),
    /// Result of `next_segment`.
    NextSegment(control_reply::SegmentStep),
    /// Result of `previous_segment`.
    PreviousSegment(control_reply::SegmentStep),
    /// Result of `requeue`.
    Requeue(control_reply::Requeued),
    /// Result of `reorder`.
    Reorder(control_reply::Reordered),
    /// Result of `cancel`.
    Cancel(control_reply::Cancelled),
    /// Result of `remove_history`.
    RemoveHistory(control_reply::HistoryRemoved),
    /// Result of `clear`.
    Clear(control_reply::Cleared),
    /// Result of `purge_cache`.
    PurgeCache(control_reply::CachePurged),
    /// Result of `status`.
    Status(Box<status::StatusReply>),
    /// Result of `metrics`.
    Metrics(metrics::MetricsReply),
    /// Result of `snapshot`.
    Snapshot(Box<snapshot::Snapshot>),
    /// Result of `voices`.
    Voices(control_reply::Voices),
    /// Result of `voice_assignments`.
    VoiceAssignments(control_reply::VoiceAssignments),
    /// Result of `assign_voice`.
    AssignVoice(control_reply::VoiceAssigned),
    /// Result of `settings`.
    Settings(control_reply::Settings),
    /// Result of `subscribe`.
    Subscribe(control_reply::Subscribed),
}

/// Decode a reply using the originating operation.
///
/// # Errors
/// Refuses over-limit input, malformed JSON, and fields outside that operation's reply.
pub fn decode_reply(operation: Operation, line: &[u8]) -> Result<Reply, WireError> {
    if let Ok(error) = decode::<ErrorReply>(line) {
        return Ok(Reply::Error(error));
    }
    match operation {
        Operation::Submit => decode(line).map(Reply::Submit),
        Operation::Engines => decode(line).map(Reply::Engines),
        Operation::ModelSetup => decode(line).map(Reply::ModelSetup),
        Operation::CancelModelSetup => decode(line).map(Reply::CancelModelSetup),
        Operation::Get => decode(line).map(Reply::Get),
        Operation::List => decode(line).map(Reply::List),
        Operation::History => decode(line).map(Reply::History),
        Operation::ExportEvidence => decode(line).map(Reply::ExportEvidence),
        Operation::RestartModel => decode(line).map(Reply::RestartModel),
        Operation::Storage => decode(line).map(Reply::Storage),
        Operation::Pause => decode(line).map(Reply::Pause),
        Operation::Resume => decode(line).map(Reply::Resume),
        Operation::ResumeWhenInputIdle => decode(line).map(Reply::ResumeWhenInputIdle),
        Operation::Skip => decode(line).map(Reply::Skip),
        Operation::Rewind => decode(line).map(Reply::Rewind),
        Operation::NextSegment => decode(line).map(Reply::NextSegment),
        Operation::PreviousSegment => decode(line).map(Reply::PreviousSegment),
        Operation::Requeue => decode(line).map(Reply::Requeue),
        Operation::Reorder => decode(line).map(Reply::Reorder),
        Operation::Cancel => decode(line).map(Reply::Cancel),
        Operation::RemoveHistory => decode(line).map(Reply::RemoveHistory),
        Operation::Clear => decode(line).map(Reply::Clear),
        Operation::PurgeCache => decode(line).map(Reply::PurgeCache),
        Operation::Status => decode(line).map(Reply::Status),
        Operation::Metrics => decode(line).map(Reply::Metrics),
        Operation::Snapshot => decode(line).map(Reply::Snapshot),
        Operation::Voices => decode(line).map(Reply::Voices),
        Operation::VoiceAssignments => decode(line).map(Reply::VoiceAssignments),
        Operation::AssignVoice => decode(line).map(Reply::AssignVoice),
        Operation::Settings => decode(line).map(Reply::Settings),
        Operation::Subscribe => decode(line).map(Reply::Subscribe),
        Operation::Provenance => decode(line).map(Reply::Provenance),
    }
}

/// Encode a reply within the local response byte ceiling.
///
/// # Errors
/// Refuses oversized serialized output.
pub fn encode_reply(reply: &Reply) -> Result<Vec<u8>, WireError> {
    encode(reply, MAX_RESPONSE_BYTES)
}
