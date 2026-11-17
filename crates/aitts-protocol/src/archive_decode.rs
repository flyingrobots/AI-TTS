// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Admission before growing historical collections.

#![deny(clippy::arithmetic_side_effects)]

use crate::archive::{
    ArchiveValue, MAX_ARCHIVE_DEPTH, MAX_ARCHIVE_ENTRIES, MAX_ARCHIVE_TEXT_BYTES,
};
use crate::value::Number;
use serde::Deserializer;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::collections::BTreeMap;
use std::fmt;

pub(crate) struct Budget {
    entries: usize,
    text: usize,
}
impl Default for Budget {
    fn default() -> Self {
        Self {
            entries: MAX_ARCHIVE_ENTRIES,
            text: MAX_ARCHIVE_TEXT_BYTES,
        }
    }
}
impl Budget {
    fn value(&mut self, depth: usize) -> Result<(), ()> {
        if depth > MAX_ARCHIVE_DEPTH {
            return Err(());
        }
        self.entries = self.entries.checked_sub(1).ok_or(())?;
        Ok(())
    }
    fn text(&mut self, value: &str) -> Result<(), ()> {
        self.text = self.text.checked_sub(value.len()).ok_or(())?;
        Ok(())
    }
    pub(crate) fn check_entries(
        &mut self,
        entries: &BTreeMap<String, ArchiveValue>,
        depth: usize,
    ) -> Result<(), ()> {
        self.value(depth)?;
        let child = depth.checked_add(1).ok_or(())?;
        for (key, value) in entries {
            self.text(key)?;
            self.check(value, child)?;
        }
        Ok(())
    }
    pub(crate) fn check(&mut self, value: &ArchiveValue, depth: usize) -> Result<(), ()> {
        self.value(depth)?;
        let child = depth.checked_add(1).ok_or(())?;
        match value {
            ArchiveValue::Text(text) => self.text(text)?,
            ArchiveValue::Array(values) => {
                for value in values {
                    self.check(value, child)?;
                }
            }
            ArchiveValue::Object(entries) => {
                for (key, value) in entries {
                    self.text(key)?;
                    self.check(value, child)?;
                }
            }
            ArchiveValue::Null | ArchiveValue::Boolean(_) | ArchiveValue::Number(_) => {}
        }
        Ok(())
    }
}

pub(crate) struct Seed<'a> {
    pub(crate) budget: &'a mut Budget,
    pub(crate) depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = ArchiveValue;
    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Self::Value, D::Error> {
        self.budget
            .value(self.depth)
            .map_err(|()| de::Error::custom("archive resource limit"))?;
        deserializer.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = ArchiveValue;
    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a bounded historical JSON value")
    }
    fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
        Ok(ArchiveValue::Null)
    }
    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Self::Value, E> {
        Ok(ArchiveValue::Boolean(value))
    }
    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Self::Value, E> {
        Ok(ArchiveValue::Number(value.into()))
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Self::Value, E> {
        Ok(ArchiveValue::Number(value.into()))
    }
    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Self::Value, E> {
        Number::from_f64(value)
            .map(ArchiveValue::Number)
            .ok_or_else(|| E::custom("nonfinite archive number"))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
        self.budget
            .text(value)
            .map_err(|()| E::custom("archive text limit"))?;
        Ok(ArchiveValue::Text(value.to_owned()))
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Self::Value, E> {
        self.budget
            .text(&value)
            .map_err(|()| E::custom("archive text limit"))?;
        Ok(ArchiveValue::Text(value))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Self::Value, A::Error> {
        let depth = self
            .depth
            .checked_add(1)
            .ok_or_else(|| de::Error::custom("archive depth limit"))?;
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element_seed(Seed {
            budget: self.budget,
            depth,
        })? {
            values.push(value);
        }
        Ok(ArchiveValue::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
        let depth = self
            .depth
            .checked_add(1)
            .ok_or_else(|| de::Error::custom("archive depth limit"))?;
        let mut entries = BTreeMap::new();
        while let Some(key) = map.next_key_seed(TextSeed(self.budget))? {
            if entries.contains_key(&key) {
                return Err(de::Error::custom("duplicate archive key"));
            }
            let value = map.next_value_seed(Seed {
                budget: self.budget,
                depth,
            })?;
            entries.insert(key, value);
        }
        Ok(ArchiveValue::Object(entries))
    }
}
struct TextSeed<'a>(&'a mut Budget);
impl<'de> DeserializeSeed<'de> for TextSeed<'_> {
    type Value = String;
    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Self::Value, D::Error> {
        deserializer.deserialize_string(self)
    }
}
impl Visitor<'_> for TextSeed<'_> {
    type Value = String;
    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a bounded archive key")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<String, E> {
        self.0
            .text(value)
            .map_err(|()| E::custom("archive text limit"))?;
        Ok(value.to_owned())
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<String, E> {
        self.0
            .text(&value)
            .map_err(|()| E::custom("archive text limit"))?;
        Ok(value)
    }
}
