// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Private admission wrapper for intentionally open legacy JSON values.

use crate::WireError;
use crate::archive::ArchiveValue;
use crate::archive_decode::{Budget, Seed};
use schemars::{JsonSchema, Schema, SchemaGenerator};
use serde::de::DeserializeSeed;
use serde::{Deserialize, Deserializer, Serialize};
use std::borrow::Cow;

/// An admitted historical value, including scalar, array, object, and null cases.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct ArchivedValue(ArchiveValue);

impl ArchivedValue {
    /// Admit a caller-constructed value before copying it into a wire message.
    ///
    /// # Errors
    /// Refuses excess depth, values, or UTF-8 text bytes under the archive limits.
    pub fn try_new(value: &ArchiveValue) -> Result<Self, WireError> {
        Budget::default()
            .check(value, 1)
            .map_err(|()| WireError::InvalidMessage)?;
        Ok(Self(value.clone()))
    }

    /// Inspect the admitted historical value without permitting mutation.
    pub const fn value(&self) -> &ArchiveValue {
        &self.0
    }
}

impl<'de> Deserialize<'de> for ArchivedValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let mut budget = Budget::default();
        (Seed {
            budget: &mut budget,
            depth: 1,
        })
        .deserialize(deserializer)
        .map(Self)
    }
}

impl JsonSchema for ArchivedValue {
    fn schema_name() -> Cow<'static, str> {
        "ArchivedValue".into()
    }
    fn json_schema(generator: &mut SchemaGenerator) -> Schema {
        let mut schema = ArchiveValue::json_schema(generator);
        schema.insert("description".into(), "Historical JSON value. The codec also enforces aggregate depth, value-count, and UTF-8 text budgets.".into());
        schema
    }
}
