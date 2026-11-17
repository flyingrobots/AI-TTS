// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Closed string vocabularies shared by the daemon wire messages.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// The utterance lifecycle on the wire.
#[derive(
    Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, JsonSchema,
)]
#[serde(remote = "Self")]
pub enum State {
    /// Accepted before queue placement.
    Submitted,
    /// Waiting for synthesis.
    Queued,
    /// Synthesis owns the work.
    Synthesizing,
    /// Audio is ready.
    Ready,
    /// Playback owns the device.
    Playing,
    /// Playback is resumable.
    Paused,
    /// Playback finished.
    Played,
    /// Playback was skipped.
    Skipped,
    /// Work was cancelled.
    Cancelled,
    /// Synthesis or playback failed.
    Failed,
}

/// Requested queue placement.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum Priority {
    /// Append to pending work.
    Normal,
    /// Queue ahead of pending work.
    Urgent,
    /// Interrupt when audio is ready.
    Preempt,
}

/// Immutable disclosure policy.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum Sensitivity {
    /// May use a remote engine.
    Public,
    /// Requires a local engine.
    Internal,
    /// Confidential text requires a local engine.
    Confidential,
}

/// Source-text interpretation.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum ContentFormat {
    /// Keep markup literal.
    PlainText,
    /// Use Markdown speech projection.
    Markdown,
}

/// Queue selected for listing.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum Queue {
    /// Input queue.
    Input,
    /// Playback queue.
    Playback,
}

/// Queue selected for an explicit clear.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum ClearQueue {
    /// Pending work except the current speaker.
    Queue,
    /// Terminal history.
    History,
    /// Input queue.
    Input,
    /// Playback queue.
    Playback,
}

/// Listener-input hold release policy.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum ResumePolicy {
    /// Require explicit resumption.
    Manual,
    /// Resume when input is idle.
    WhenIdle,
}

/// Observable playback-worker activity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum PlaybackState {
    /// No active speech.
    Idle,
    /// Audio is being prepared.
    Synthesizing,
    /// Speech is playing.
    Playing,
    /// Playback is held.
    Paused,
}

/// What accepted speech will do next.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum SubmissionDisposition {
    /// Queued for playback.
    QueuedForPlayback,
    /// Spooling while playback is held.
    SpooledUntilResume,
    /// Generate audio for the client without host playback.
    SynthesisOnly,
}

/// Reported model readiness and setup state.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self")]
pub enum ModelState {
    /// Not loaded.
    #[serde(rename = "cold")]
    Cold,
    /// Loading model.
    #[serde(rename = "loading")]
    Loading,
    /// Model is ready.
    #[serde(rename = "ready")]
    Ready,
    /// Restarting model.
    #[serde(rename = "reloading")]
    Reloading,
    /// Model or setup failed.
    #[serde(rename = "failed")]
    Failed,
    /// An external server owns the model.
    #[serde(rename = "server managed")]
    ServerManaged,
    /// No installed runtime.
    #[serde(rename = "not installed")]
    NotInstalled,
    /// Setup is active.
    #[serde(rename = "installing")]
    Installing,
    /// Setup was cancelled.
    #[serde(rename = "cancelled")]
    Cancelled,
}

/// Identity of an installed managed adapter.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", rename_all = "snake_case")]
pub enum AdapterStatus {
    /// Installed digest matches the daemon package.
    Current,
    /// Installed digest differs.
    Stale,
    /// A legacy runtime has no valid digest.
    Unknown,
}

crate::strict::string_only!(
    State,
    Priority,
    Sensitivity,
    ContentFormat,
    Queue,
    ClearQueue,
    ResumePolicy,
    PlaybackState,
    SubmissionDisposition,
    ModelState,
    AdapterStatus
);
