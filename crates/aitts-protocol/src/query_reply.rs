// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Closed replies for individual control and query operations.

use crate::catalog::{Engine, Model};
use crate::metrics::{StorageEntry, StorageReceipt};
use crate::utterance::Utterance;
use crate::value::{Nullable, Success};
use crate::vocabulary::{ModelState, Sensitivity, State, SubmissionDisposition};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// An operation completed without additional result fields.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Acknowledged {
    /// ok.
    pub ok: Success,
}

/// The daemon accepted speech with this queue disposition.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Submitted {
    /// ok.
    pub ok: Success,
    /// accepted.
    pub accepted: Success,
    /// id.
    pub id: String,
    /// state.
    pub state: State,
    /// playback.
    pub playback: bool,
    /// voice.
    pub voice: String,
    /// sensitivity.
    pub sensitivity: Sensitivity,
    /// segment count.
    pub segment_count: u64,
    /// composite.
    pub composite: bool,
    /// eligible engines.
    pub eligible_engines: Vec<String>,
    /// accepting speech.
    pub accepting_speech: Success,
    /// playback held.
    pub playback_held: bool,
    /// submission disposition.
    pub submission_disposition: SubmissionDisposition,
    /// submission guidance.
    pub submission_guidance: String,
}

/// The active engine and model setup catalogs.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Engines {
    /// ok.
    pub ok: Success,
    /// engines.
    pub engines: Vec<Engine>,
    /// models.
    pub models: Vec<Model>,
}

/// An explicit setup request's initial state.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ModelSetup {
    /// ok.
    pub ok: Success,
    /// state.
    pub state: ModelState,
}

/// One utterance.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Item {
    /// ok.
    pub ok: Success,
    /// item.
    pub item: Utterance,
}

/// A queue or history projection.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Items {
    /// ok.
    pub ok: Success,
    /// items.
    pub items: Vec<Utterance>,
}

/// The evidence export destination and warnings.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Exported {
    /// ok.
    pub ok: Success,
    /// path.
    pub path: String,
    /// warnings.
    pub warnings: Vec<String>,
}

/// Cache inventory and the optional deletion receipt.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Storage {
    /// ok.
    pub ok: Success,
    /// entries.
    pub entries: Vec<StorageEntry>,
    /// total bytes.
    pub total_bytes: u64,
    /// retention days.
    pub retention_days: u64,
    /// receipt.
    pub receipt: Nullable<StorageReceipt>,
}

crate::strict::object_only!(
    Acknowledged,
    Submitted,
    Engines,
    ModelSetup,
    Item,
    Items,
    Exported,
    Storage
);
