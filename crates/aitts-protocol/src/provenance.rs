// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Provenance separates closed daemon fields from bounded archived evidence.

use crate::archived_value::ArchivedValue;
use crate::evidence::Evidence;
use crate::evidence_fields::{AudioFields, GenerationFields, ModelFields};
use crate::value::{Nullable, Number, Success};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// The provenance operation reply.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ProvenanceReply {
    /// ok.
    pub ok: Success,
    /// provenance.
    pub provenance: Provenance,
}

/// Resolved utterance identity and saved synthesis evidence.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Provenance {
    /// origin.
    pub origin: String,
    /// caller source.
    pub caller_source: Nullable<String>,
    /// arguments.
    pub arguments: ArchivedValue,
    /// source blake3.
    pub source_blake3: String,
    /// resolved voice.
    pub resolved_voice: String,
    /// resolved speed.
    pub resolved_speed: Number,
    /// replay of.
    pub replay_of: Nullable<String>,
    /// submitted at.
    pub submitted_at: Number,
    /// clips.
    pub clips: Vec<Clip>,
}

/// Historical records for one generated artifact.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct Clip {
    /// artifact id.
    pub artifact_id: String,
    /// generation.
    pub generation: Nullable<Evidence<GenerationFields>>,
    /// model.
    pub model: Nullable<Evidence<ModelFields>>,
    /// audio.
    pub audio: Nullable<Evidence<AudioFields>>,
}

crate::strict::object_only!(ProvenanceReply, Provenance, Clip);
