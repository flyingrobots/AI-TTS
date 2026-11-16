// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Typed known evidence fields alongside bounded historical extensions.

use crate::archive::{ArchiveObject, ArchiveValue};
use schemars::{JsonSchema, Schema, SchemaGenerator};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::borrow::Cow;

/// Known fields in a historical metadata object.
pub trait Metadata: DeserializeOwned + JsonSchema {
    /// Keys whose values this producer defines.
    const FIELDS: &'static [&'static str];
}

/// Immutable historical metadata with a validated typed view of its known fields.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Evidence<T> {
    known: T,
    original: ArchiveObject,
}
impl<T> Evidence<T> {
    /// The typed fields supplied by known producers.
    pub const fn known(&self) -> &T {
        &self.known
    }
    /// Original historical keys and values, including unknown producer extensions.
    pub const fn original(&self) -> &ArchiveObject {
        &self.original
    }
}
impl<T> Serialize for Evidence<T> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.original.serialize(serializer)
    }
}
impl<'de, T: Metadata> Deserialize<'de> for Evidence<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let original = ArchiveObject::deserialize(deserializer)?;
        let selected: std::collections::BTreeMap<_, _> = original
            .entries()
            .iter()
            .filter(|(key, _)| T::FIELDS.contains(&key.as_str()))
            .collect();
        // This conversion is bounded by the already-admitted archive, not an open envelope.
        let selected = serde_json::to_value(selected).map_err(serde::de::Error::custom)?;
        let known = serde_json::from_value(selected).map_err(serde::de::Error::custom)?;
        Ok(Self { known, original })
    }
}
impl<T: Metadata> JsonSchema for Evidence<T> {
    fn schema_name() -> Cow<'static, str> {
        format!("Evidence_{}", T::schema_name()).into()
    }
    fn schema_id() -> Cow<'static, str> {
        format!("aitts_protocol::Evidence<{}>", T::schema_id()).into()
    }
    fn json_schema(generator: &mut SchemaGenerator) -> Schema {
        let mut schema = T::json_schema(generator);
        schema.insert(
            "additionalProperties".into(),
            generator.subschema_for::<ArchiveValue>().into(),
        );
        schema
    }
}
