// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Metrics and storage inventory records.

use crate::value::{Nullable, Number, Success};
use crate::vocabulary::State;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// The daemon's in-memory timing and capacity metrics.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct MetricsReply {
    /// ok.
    pub ok: Success,
    /// counts.
    pub counts: BTreeMap<State, u64>,
    /// queue depth.
    pub queue_depth: QueueDepth,
    /// cache.
    pub cache: Cache,
    /// synthesis wait ms.
    pub synthesis_wait_ms: Nullable<Statistics>,
    /// synthesis duration ms.
    pub synthesis_duration_ms: Nullable<Statistics>,
    /// playback wait ms.
    pub playback_wait_ms: Nullable<Statistics>,
    /// playback failures.
    pub playback_failures: u64,
}

/// Current queue lengths.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct QueueDepth {
    /// input.
    pub input: u64,
    /// playback.
    pub playback: u64,
}

/// Current cache usage and configured ceiling.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Cache {
    /// bytes.
    pub bytes: u64,
    /// max bytes.
    pub max_bytes: u64,
}

/// Timing samples in milliseconds; clock adjustments can yield negative values.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Statistics {
    /// count.
    pub count: u64,
    /// p50.
    pub p50: Number,
    /// p95.
    pub p95: Number,
    /// max.
    pub max: Number,
}

/// One cache-storage inventory entry.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct StorageEntry {
    /// id.
    pub id: String,
    /// bytes.
    pub bytes: u64,
    /// modified at.
    pub modified_at: Number,
    /// protected.
    pub protected: bool,
    /// preview.
    pub preview: String,
}

/// Counts from an explicit storage deletion.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct StorageReceipt {
    /// removed.
    pub removed: u64,
    /// protected.
    pub protected: u64,
    /// failed.
    pub failed: u64,
}
