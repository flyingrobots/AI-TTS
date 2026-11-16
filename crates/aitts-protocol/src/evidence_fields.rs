// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Known fields in persisted generation, model, and audio evidence.

use crate::evidence::Metadata;
use crate::value::{Nullable, Number, Presence};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Known generation evidence. Legacy records may omit fields.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct GenerationFields {
    /// artifact id.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub artifact_id: Presence<String>,
    /// utterance id.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub utterance_id: Presence<String>,
    /// segment index.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub segment_index: Presence<Nullable<u64>>,
    /// voice.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub voice: Presence<String>,
    /// speed.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub speed: Presence<Number>,
    /// engine.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub engine: Presence<String>,
    /// captured at.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub captured_at: Presence<Number>,
    /// runtime.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub runtime: Presence<RuntimeMetadata>,
}

impl Metadata for GenerationFields {
    const FIELDS: &'static [&'static str] = &[
        "artifact_id",
        "utterance_id",
        "segment_index",
        "voice",
        "speed",
        "engine",
        "captured_at",
        "runtime",
    ];
}

/// Known audio evidence. Legacy records may omit fields.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct AudioFields {
    /// blake3.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub blake3: Presence<String>,
    /// sha256.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub sha256: Presence<String>,
    /// sample rate.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub sample_rate: Presence<u64>,
    /// channels.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub channels: Presence<u64>,
    /// frames.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub frames: Presence<u64>,
    /// subtype.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub subtype: Presence<String>,
    /// peak.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub peak: Presence<Number>,
    /// clipped samples.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub clipped_samples: Presence<u64>,
    /// nonfinite samples.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub nonfinite_samples: Presence<u64>,
}

impl Metadata for AudioFields {
    const FIELDS: &'static [&'static str] = &[
        "blake3",
        "sha256",
        "sample_rate",
        "channels",
        "frames",
        "subtype",
        "peak",
        "clipped_samples",
        "nonfinite_samples",
    ];
}

/// Known adapter evidence; runtime-specific extensions remain archival.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct ModelFields {
    /// repository.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub repository: Presence<String>,
    /// files.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub files: Presence<BTreeMap<String, ModelFile>>,
    /// torch threads.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub torch_threads: Presence<u64>,
    /// torch interop threads.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub torch_interop_threads: Presence<u64>,
    /// model training.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub model_training: Presence<Nullable<bool>>,
    /// device.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub device: Presence<Nullable<String>>,
    /// voice.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub voice: Presence<String>,
    /// watermark.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub watermark: Presence<String>,
    /// backend.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub backend: Presence<String>,
    /// model.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub model: Presence<String>,
    /// host.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub host: Presence<String>,
    /// model identity.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub model_identity: Presence<String>,
    /// port.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub port: Presence<u16>,
    /// runtime.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub runtime: Presence<RuntimeMetadata>,
}

impl Metadata for ModelFields {
    const FIELDS: &'static [&'static str] = &[
        "repository",
        "files",
        "torch_threads",
        "torch_interop_threads",
        "model_training",
        "device",
        "voice",
        "watermark",
        "backend",
        "model",
        "host",
        "model_identity",
        "port",
        "runtime",
    ];
}

/// A model file's content identity and size.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct ModelFile {
    /// sha256.
    pub sha256: String,
    /// bytes.
    pub bytes: u64,
}

/// Known runtime evidence from the daemon or worker.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct RuntimeMetadata {
    /// os.
    pub os: String,
    /// os release.
    pub os_release: String,
    /// macos.
    pub macos: String,
    /// architecture.
    pub architecture: String,
    /// python.
    pub python: String,
    /// cpu count.
    pub cpu_count: Nullable<u64>,
    /// packages.
    pub packages: BTreeMap<String, Nullable<String>>,
}
