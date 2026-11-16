// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Full daemon status, including admission and the current playback projection.

use crate::utterance::Utterance;
use crate::value::{Nullable, Number, Success};
use crate::vocabulary::{PlaybackState, State, SubmissionDisposition};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Status embedded in an atomic snapshot.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Status {
    /// version.
    pub version: String,
    /// state.
    pub state: Accepting,
    /// accepting speech.
    pub accepting_speech: Success,
    /// playback held.
    pub playback_held: bool,
    /// submission disposition.
    pub submission_disposition: SubmissionDisposition,
    /// submission guidance.
    pub submission_guidance: String,
    /// playback state.
    pub playback_state: PlaybackState,
    /// input active.
    pub input_active: Nullable<bool>,
    /// interruption.
    pub interruption: Nullable<Interruption>,
    /// current.
    pub current: Nullable<Utterance>,
    /// counts.
    pub counts: BTreeMap<State, u64>,
    /// engine.
    pub engine: String,
    /// engine preparing.
    pub engine_preparing: Nullable<EnginePreparation>,
    /// voice.
    pub voice: String,
}

/// The status operation reply.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct StatusReply {
    /// ok.
    pub ok: Success,
    /// version.
    pub version: String,
    /// state.
    pub state: Accepting,
    /// accepting speech.
    pub accepting_speech: Success,
    /// playback held.
    pub playback_held: bool,
    /// submission disposition.
    pub submission_disposition: SubmissionDisposition,
    /// submission guidance.
    pub submission_guidance: String,
    /// playback state.
    pub playback_state: PlaybackState,
    /// input active.
    pub input_active: Nullable<bool>,
    /// interruption.
    pub interruption: Nullable<Interruption>,
    /// current.
    pub current: Nullable<Utterance>,
    /// counts.
    pub counts: BTreeMap<State, u64>,
    /// engine.
    pub engine: String,
    /// engine preparing.
    pub engine_preparing: Nullable<EnginePreparation>,
    /// voice.
    pub voice: String,
}

/// A listener-input hold.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Interruption {
    /// reason.
    pub reason: ListenerSpeaking,
    /// at.
    pub at: Number,
    /// resume armed.
    pub resume_armed: bool,
}

/// The model asset being prepared and its start timestamp.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct EnginePreparation {
    /// asset.
    pub asset: String,
    /// since.
    pub since: Number,
}

/// The literal `accepting` discriminator.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum Accepting {
    /// The supported discriminator value.
    #[serde(rename = "accepting")]
    Value,
}

/// The literal `listener_speaking` discriminator.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum ListenerSpeaking {
    /// The supported discriminator value.
    #[serde(rename = "listener_speaking")]
    Value,
}

/// The literal `input_idle` discriminator.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum InputIdle {
    /// The supported discriminator value.
    #[serde(rename = "input_idle")]
    Value,
}
