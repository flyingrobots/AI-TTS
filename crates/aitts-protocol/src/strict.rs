// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Shape-strict serde entry points for closed records and string vocabularies.
//!
//! Derived serde code also admits a JSON array for a struct (in field order) and
//! a single-entry object for a unit variant. A wrapping deserializer in the codec
//! cannot remove those forms, because internally tagged and untagged enums buffer
//! nested values into serde's private content representation and decode them
//! later without it. These macros therefore refuse the alternative forms at each
//! type. Each type keeps its derive under `#[serde(remote = "Self")]`, which turns
//! the derived code into inherent functions that the trait impls below delegate to.

/// Implement `Serialize` and a map-only `Deserialize` over a `remote = "Self"` derive.
macro_rules! object_only {
    ($($record:ty),+ $(,)?) => {$(
        impl ::serde::Serialize for $record {
            fn serialize<S: ::serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
                <$record>::serialize(self, serializer)
            }
        }
        impl<'de> ::serde::Deserialize<'de> for $record {
            fn deserialize<D: ::serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                struct ObjectVisitor;
                impl<'de> ::serde::de::Visitor<'de> for ObjectVisitor {
                    type Value = $record;
                    fn expecting(&self, formatter: &mut ::core::fmt::Formatter<'_>) -> ::core::fmt::Result {
                        formatter.write_str(concat!("a JSON object for ", stringify!($record)))
                    }
                    fn visit_map<A: ::serde::de::MapAccess<'de>>(self, map: A) -> Result<$record, A::Error> {
                        <$record>::deserialize(::serde::de::value::MapAccessDeserializer::new(map))
                    }
                }
                deserializer.deserialize_map(ObjectVisitor)
            }
        }
    )+};
}

/// Implement `Serialize` and a string-only `Deserialize` over a `remote = "Self"` derive.
macro_rules! string_only {
    ($($vocabulary:ty),+ $(,)?) => {$(
        impl ::serde::Serialize for $vocabulary {
            fn serialize<S: ::serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
                <$vocabulary>::serialize(self, serializer)
            }
        }
        impl<'de> ::serde::Deserialize<'de> for $vocabulary {
            fn deserialize<D: ::serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                struct StringVisitor;
                impl ::serde::de::Visitor<'_> for StringVisitor {
                    type Value = $vocabulary;
                    fn expecting(&self, formatter: &mut ::core::fmt::Formatter<'_>) -> ::core::fmt::Result {
                        formatter.write_str(concat!("a JSON string for ", stringify!($vocabulary)))
                    }
                    fn visit_str<E: ::serde::de::Error>(self, value: &str) -> Result<$vocabulary, E> {
                        <$vocabulary>::deserialize(::serde::de::value::StrDeserializer::<E>::new(value))
                    }
                }
                deserializer.deserialize_str(StringVisitor)
            }
        }
    )+};
}

pub(crate) use {object_only, string_only};
