// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Typed setting fields; applying settings and catalog validation remain application work.

use crate::value::{Number, Presence};
use crate::vocabulary::ResumePolicy;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// The two supported cache-limit wire kinds; canonical decimal validation is application policy.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum CacheLimit {
    /// A nonnegative integer byte count.
    Bytes(u64),
    /// A decimal string from the settings boundary.
    Decimal(String),
}

/// Partial settings fields. An omitted field implies no update.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SettingsUpdate {
    /// Engine selected for future admissions.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub engine: Presence<String>,
    /// Selected voice.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub voice: Presence<String>,
    /// Automatic allocation languages.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub voice_languages: Presence<Vec<String>>,
    /// Generation speed.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub speed: Presence<Number>,
    /// Live playback multiplier.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub playback_rate: Presence<Number>,
    /// Cache capacity in bytes.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub cache_max_bytes: Presence<CacheLimit>,
    /// Caption preference.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub captions_enabled: Presence<bool>,
    /// Earcon preference.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub earcon_enabled: Presence<bool>,
    /// Audio ducking preference.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub ducking_enabled: Presence<bool>,
    /// Whether listener input interrupts playback.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub input_interrupt_enabled: Presence<bool>,
    /// Policy for releasing listener-input holds.
    #[serde(default, skip_serializing_if = "Presence::is_absent")]
    pub input_interrupt_resume: Presence<ResumePolicy>,
}

/// All public settings, including the read-only caption configuration flag.
#[expect(
    clippy::struct_excessive_bools,
    reason = "independent booleans are fixed by the existing wire contract"
)]
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SettingsSnapshot {
    /// Engine selected for future admissions.
    pub engine: String,
    /// Selected voice.
    pub voice: String,
    /// Automatic allocation languages.
    pub voice_languages: Vec<String>,
    /// Generation speed.
    pub speed: Number,
    /// Live playback multiplier.
    pub playback_rate: Number,
    /// Cache capacity in bytes.
    pub cache_max_bytes: u64,
    /// Caption preference.
    pub captions_enabled: bool,
    /// Earcon preference.
    pub earcon_enabled: bool,
    /// Audio ducking preference.
    pub ducking_enabled: bool,
    /// Whether listener input interrupts playback.
    pub input_interrupt_enabled: bool,
    /// Policy for releasing listener-input holds.
    pub input_interrupt_resume: ResumePolicy,
    /// Whether a caption preference was configured.
    pub captions_enabled_configured: bool,
}

crate::strict::object_only!(SettingsUpdate, SettingsSnapshot);
