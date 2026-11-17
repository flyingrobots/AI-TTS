// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns scalar settings validation. It does not apply settings.
//!
//! A wire adapter must preserve value kinds: a boolean is never a number.
//! Engine and voice catalogs are observations supplied by the caller.

#![deny(clippy::arithmetic_side_effects)]

use crate::voices::{LANGUAGE_CODES, automatic_pool};
use alloc::{string::ToString, vec::Vec};
use core::fmt;

/// A setting value before validation, with its wire kind preserved.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Value<'a> {
    /// An integer value, without conversion through a floating point number.
    Integer(i128),
    /// A floating point number.
    Number(f64),
    /// A string value.
    Text(&'a str),
    /// A boolean value.
    Boolean(bool),
}

/// The setting cannot accept this value or caller-supplied catalog.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InvalidSetting {
    /// The supplied catalog exceeds the bounded allocation allowance.
    Collection(crate::CollectionLimit),
    /// Speed must be a finite number in the inclusive range 0.5 to 2.0.
    Speed,
    /// Rate must be one of the six supported playback rates.
    PlaybackRate,
    /// Cache size must be a non-negative whole byte count representable by `u64`.
    CacheLimit,
    /// Toggle settings accept only a wire boolean.
    Boolean,
    /// Resume policy must be `manual` or `when_idle`.
    ResumePolicy,
    /// A selected language is absent, unknown, or leaves no eligible voice.
    Languages,
    /// The selected name is absent from the supplied catalog.
    UnknownName,
}

impl fmt::Display for InvalidSetting {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid setting: {self:?}")
    }
}
impl core::error::Error for InvalidSetting {}

/// A validated synthesis speed.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Speed(f64);
impl Speed {
    /// Parse a numeric speed without accepting booleans or numeric strings.
    ///
    /// # Errors
    /// Returns `InvalidSetting::Speed` for unsupported kinds or values.
    pub fn parse(value: Value<'_>) -> Result<Self, InvalidSetting> {
        let speed = match value {
            Value::Number(speed) => speed,
            Value::Integer(1) => 1.0,
            Value::Integer(2) => 2.0,
            _ => return Err(InvalidSetting::Speed),
        };
        if (0.5..=2.0).contains(&speed) {
            Ok(Self(speed))
        } else {
            Err(InvalidSetting::Speed)
        }
    }
    /// Validated speed multiplier.
    pub const fn multiplier(self) -> f64 {
        self.0
    }
}

/// A supported playback rate.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PlaybackRate(f64);
impl PlaybackRate {
    /// Parse one of the offered playback rates.
    ///
    /// # Errors
    /// Returns `InvalidSetting::PlaybackRate` for any other value or kind.
    pub fn parse(value: Value<'_>) -> Result<Self, InvalidSetting> {
        let rate = match value {
            Value::Number(rate) => rate,
            Value::Integer(1) => 1.0,
            Value::Integer(2) => 2.0,
            Value::Integer(3) => 3.0,
            _ => return Err(InvalidSetting::PlaybackRate),
        };
        if [0.5, 0.75, 1.0, 1.5, 2.0, 3.0].contains(&rate) {
            Ok(Self(rate))
        } else {
            Err(InvalidSetting::PlaybackRate)
        }
    }
    /// Validated playback multiplier.
    pub const fn multiplier(self) -> f64 {
        self.0
    }
}

/// A whole byte count for cache limits and retention accounting.
#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
pub struct Bytes(pub u64);
impl Bytes {
    /// Parse a whole integer or its canonical decimal string (surrounding space allowed).
    ///
    /// # Errors
    /// Returns `InvalidSetting::CacheLimit` on malformed, negative, or overflowing input.
    pub fn parse(value: Value<'_>) -> Result<Self, InvalidSetting> {
        let limit = match value {
            Value::Integer(value) => {
                u64::try_from(value).map_err(|_| InvalidSetting::CacheLimit)?
            }
            Value::Text(raw) => {
                let trimmed = raw.trim();
                let parsed: u64 = trimmed.parse().map_err(|_| InvalidSetting::CacheLimit)?;
                if trimmed != parsed.to_string() {
                    return Err(InvalidSetting::CacheLimit);
                }
                parsed
            }
            _ => return Err(InvalidSetting::CacheLimit),
        };
        Ok(Self(limit))
    }
}

/// A hold caused by listener input is released manually or after idle detection.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResumePolicy {
    /// Require an explicit resume.
    Manual,
    /// Resume when the caller observes that input is idle.
    WhenIdle,
}
impl ResumePolicy {
    /// Parse the two wire policy names.
    ///
    /// # Errors
    /// Returns `InvalidSetting::ResumePolicy` for any other value.
    pub fn parse(value: Value<'_>) -> Result<Self, InvalidSetting> {
        match value {
            Value::Text("manual") => Ok(Self::Manual),
            Value::Text("when_idle") => Ok(Self::WhenIdle),
            _ => Err(InvalidSetting::ResumePolicy),
        }
    }
}

/// Validate a toggle without accepting truthy strings or numbers.
///
/// # Errors
/// Returns `InvalidSetting::Boolean` unless the value is a boolean.
pub fn boolean(value: Value<'_>) -> Result<bool, InvalidSetting> {
    match value {
        Value::Boolean(value) => Ok(value),
        _ => Err(InvalidSetting::Boolean),
    }
}

/// Validate an engine or voice name against the caller's selected engine catalog.
///
/// # Errors
/// Returns `InvalidSetting::UnknownName` for absent names or other value kinds.
pub fn catalog_name<'a>(value: Value<'a>, catalog: &[&str]) -> Result<&'a str, InvalidSetting> {
    match value {
        Value::Text(name) if catalog.contains(&name) => Ok(name),
        _ => Err(InvalidSetting::UnknownName),
    }
}

/// Canonicalize a nonempty language selection and verify it leaves usable voices.
///
/// # Errors
/// Returns `InvalidSetting::Languages` for an empty, unknown, or unusable selection.
pub fn languages(selected: &[&str], catalog: &[&str]) -> Result<Vec<&'static str>, InvalidSetting> {
    if selected.is_empty() || selected.iter().any(|code| !LANGUAGE_CODES.contains(code)) {
        return Err(InvalidSetting::Languages);
    }
    let canonical: Vec<_> = LANGUAGE_CODES
        .into_iter()
        .filter(|code| selected.contains(code))
        .collect();
    if automatic_pool(catalog, &canonical)
        .map_err(InvalidSetting::Collection)?
        .is_empty()
    {
        Err(InvalidSetting::Languages)
    } else {
        Ok(canonical)
    }
}
