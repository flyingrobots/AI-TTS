// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Structured daemon errors; transport decode errors remain separate.

use schemars::{JsonSchema, Schema, SchemaGenerator};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::borrow::Cow;

/// The literal false flag in a daemon error reply.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Failure;
impl Serialize for Failure {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_bool(false)
    }
}
impl<'de> Deserialize<'de> for Failure {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        if bool::deserialize(deserializer)? {
            Err(serde::de::Error::custom("expected failure flag"))
        } else {
            Ok(Self)
        }
    }
}
impl JsonSchema for Failure {
    fn schema_name() -> Cow<'static, str> {
        "Failure".into()
    }
    fn json_schema(_generator: &mut SchemaGenerator) -> Schema {
        schemars::json_schema!({"type":"boolean","const":false})
    }
}

/// The four daemon error categories.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    /// Malformed or unsupported request.
    BadRequest,
    /// No matching object.
    NotFound,
    /// The operation is invalid in the current lifecycle state.
    IllegalState,
    /// An internal daemon failure.
    Internal,
}
/// An application error supplied by the daemon.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct DaemonError {
    /// Error category.
    pub r#type: ErrorCode,
    /// Daemon explanation.
    pub message: String,
}

/// An operation failed.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct ErrorReply {
    /// ok.
    pub ok: Failure,
    /// error.
    pub error: DaemonError,
}
