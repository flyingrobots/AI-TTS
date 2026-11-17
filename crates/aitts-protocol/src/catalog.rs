// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Model catalogs and explicit caller voice assignments.

use crate::value::{Nullable, Number, Presence};
use crate::vocabulary::{AdapterStatus, ModelState};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// An engine known to the daemon.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Engine {
    /// name.
    pub name: String,
    /// is local.
    pub is_local: bool,
    /// voices.
    pub voices: Vec<String>,
    /// state.
    pub state: ModelState,
    /// selected.
    pub selected: bool,
}

/// A model available for explicit setup.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Model {
    /// name.
    pub name: String,
    /// title.
    pub title: String,
    /// description.
    pub description: String,
    /// installed.
    pub installed: bool,
    /// selected.
    pub selected: bool,
    /// state.
    pub state: ModelState,
    /// message.
    pub message: String,
    /// incompatible.
    pub incompatible: Nullable<String>,
    /// Managed adapter identity; absence retains older producer messages.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub adapter_status: Presence<Nullable<AdapterStatus>>,
}

/// A caller's allocated or pinned voice.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Assignment {
    /// source.
    pub source: String,
    /// voice.
    pub voice: String,
    /// pinned.
    pub pinned: bool,
    /// assigned at.
    pub assigned_at: Number,
}

crate::strict::object_only!(Engine, Model, Assignment);
