// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The daemon's atomic UI snapshot.

use crate::catalog::{Assignment, Engine, Model};
use crate::settings::SettingsSnapshot;
use crate::status::Status;
use crate::utterance::Utterance;
use crate::value::{Number, Success};
use crate::vocabulary::ModelState;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// All UI state captured by one operation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    /// ok.
    pub ok: Success,
    /// status.
    pub status: Status,
    /// runtime.
    pub runtime: Runtime,
    /// playback.
    pub playback: Vec<Utterance>,
    /// input.
    pub input: Vec<Utterance>,
    /// plan.
    pub plan: Vec<Utterance>,
    /// history.
    pub history: Vec<Utterance>,
    /// voices.
    pub voices: Vec<String>,
    /// engines.
    pub engines: Vec<Engine>,
    /// models.
    pub models: Vec<Model>,
    /// voice assignments.
    pub voice_assignments: Vec<Assignment>,
    /// settings.
    pub settings: SettingsSnapshot,
}

/// Process and model state in a snapshot.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Runtime {
    /// pid.
    pub pid: u64,
    /// uptime seconds.
    pub uptime_seconds: Number,
    /// model state.
    pub model_state: ModelState,
    /// active synthesis.
    pub active_synthesis: u64,
}
