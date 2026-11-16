// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Bounded, intentionally open historical data, never a request or reply envelope.

use crate::archive_decode::{Budget, Seed};
use crate::value::Number;
use schemars::{JsonSchema, Schema, SchemaGenerator};
use serde::de::DeserializeSeed;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::borrow::Cow;
use std::collections::BTreeMap;

/// Maximum nested value depth, counting the root object as depth one.
pub const MAX_ARCHIVE_DEPTH: usize = 32;
/// Maximum values in one archive, including containers and scalar leaves.
pub const MAX_ARCHIVE_ENTRIES: usize = 4096;
/// Maximum combined UTF-8 bytes in all keys and string values in one archive.
pub const MAX_ARCHIVE_TEXT_BYTES: usize = 65_536;

/// A historical JSON value. Only an `ArchiveObject` admits a complete archive.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, JsonSchema)]
#[serde(untagged)]
pub enum ArchiveValue {
    /// JSON null.
    Null,
    /// A boolean.
    Boolean(bool),
    /// A JSON number.
    Number(Number),
    /// UTF-8 text.
    Text(String),
    /// Ordered historical values.
    Array(Vec<Self>),
    /// Historical named fields, including producer extensions.
    Object(BTreeMap<String, Self>),
}

/// An admitted historical object. Its private map prevents unchecked mutation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArchiveObject(BTreeMap<String, ArchiveValue>);

impl ArchiveObject {
    /// Inspect preserved historical entries.
    pub const fn entries(&self) -> &BTreeMap<String, ArchiveValue> {
        &self.0
    }

    /// Admit caller-constructed data under the same limits as decoded data.
    ///
    /// # Errors
    /// Refuses excess depth, values, or UTF-8 text bytes.
    pub fn try_new(entries: &BTreeMap<String, ArchiveValue>) -> Result<Self, crate::WireError> {
        Budget::default()
            .check_entries(entries, 1)
            .map_err(|()| crate::WireError::InvalidMessage)?;
        Ok(Self(entries.clone()))
    }
}
impl Serialize for ArchiveObject {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.0.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for ArchiveObject {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let mut budget = Budget::default();
        match (Seed {
            budget: &mut budget,
            depth: 1,
        })
        .deserialize(deserializer)?
        {
            ArchiveValue::Object(entries) => Ok(Self(entries)),
            _ => Err(serde::de::Error::custom("archive must be an object")),
        }
    }
}
impl JsonSchema for ArchiveObject {
    fn schema_name() -> Cow<'static, str> {
        "ArchiveObject".into()
    }
    fn json_schema(generator: &mut SchemaGenerator) -> Schema {
        let mut schema = <BTreeMap<String, ArchiveValue>>::json_schema(generator);
        schema.insert("maxProperties".into(), (MAX_ARCHIVE_ENTRIES - 1).into());
        schema.insert("description".into(), "Historical object. The codec also enforces aggregate depth, value-count, and UTF-8 text budgets.".into());
        schema
    }
}
