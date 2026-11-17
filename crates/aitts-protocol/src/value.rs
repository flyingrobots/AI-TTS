// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Values which keep wire absence, null, and numeric kinds distinct.

use schemars::{JsonSchema, Schema, SchemaGenerator};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::borrow::Cow;

/// A JSON number which retains integer versus floating-point representation.
pub type Number = serde_json::Number;

/// A field which can be absent. `Present(Nullable::Null)` retains explicit null.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum Presence<T> {
    /// The containing object did not supply this field.
    #[default]
    Absent,
    /// The containing object supplied this exact typed value.
    Present(T),
}
impl<T> Presence<T> {
    /// Whether serialization must omit this object member.
    pub const fn is_absent(&self) -> bool {
        matches!(self, Self::Absent)
    }
}
impl<T: Serialize> Serialize for Presence<T> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Absent => serializer.serialize_unit(),
            Self::Present(value) => value.serialize(serializer),
        }
    }
}
impl<'de, T: Deserialize<'de>> Deserialize<'de> for Presence<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        T::deserialize(deserializer).map(Self::Present)
    }
}
impl<T: JsonSchema> JsonSchema for Presence<T> {
    fn schema_name() -> Cow<'static, str> {
        format!("Presence_{}", T::schema_name()).into()
    }
    fn schema_id() -> Cow<'static, str> {
        format!("aitts_protocol::Presence<{}>", T::schema_id()).into()
    }
    fn json_schema(generator: &mut SchemaGenerator) -> Schema {
        generator.subschema_for::<T>()
    }
    fn inline_schema() -> bool {
        true
    }
}

/// A required JSON value which may explicitly be null. Absence is an error.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum Nullable<T> {
    /// A present non-null typed value.
    Value(T),
    /// An explicit JSON null.
    Null,
}

/// The literal success value; a false `ok` flag cannot inhabit this type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Success;
impl Serialize for Success {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_bool(true)
    }
}
impl<'de> Deserialize<'de> for Success {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        if bool::deserialize(deserializer)? {
            Ok(Self)
        } else {
            Err(serde::de::Error::custom("expected success flag"))
        }
    }
}
impl JsonSchema for Success {
    fn schema_name() -> Cow<'static, str> {
        "Success".into()
    }
    fn json_schema(_generator: &mut SchemaGenerator) -> Schema {
        schemars::json_schema!({"type":"boolean", "const":true})
    }
}
