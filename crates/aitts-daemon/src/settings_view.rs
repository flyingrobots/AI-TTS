// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the read-only settings view, as Python `SettingsService.values`.

use aitts_domain::settings::{Bytes, PlaybackRate, Value};
use aitts_domain::voices::LANGUAGE_CODES;
use aitts_protocol::settings::SettingsSnapshot;
use aitts_protocol::vocabulary::ResumePolicy;
use aitts_store::Store;

use crate::projection::number;
use crate::runtime::EngineView;

/// The Python `DEFAULT_CACHE_MAX_BYTES`: one GiB.
pub(crate) const DEFAULT_CACHE_MAX_BYTES: u64 = 1024 * 1024 * 1024;

/// Every setting as the wire reports it.
///
/// # Errors
/// Returns the store error when a read fails.
pub(crate) fn snapshot(
    store: &Store,
    engine: &EngineView,
) -> aitts_store::Result<SettingsSnapshot> {
    let settings = store.settings();
    let flag = |key: &str, default: &str| -> aitts_store::Result<bool> {
        Ok(settings.get(key, default)? == "true")
    };
    Ok(SettingsSnapshot {
        engine: engine.name.clone(),
        voice: speaking_voice(store, engine)?,
        voice_languages: languages(&settings.get("voice_languages", "en")?),
        speed: number(settings.get("speed", "1.0")?.trim().parse().unwrap_or(1.0)),
        playback_rate: number(playback_rate(&settings.get("playback_rate", "1.0")?)),
        cache_max_bytes: cache_limit(&settings.get("cache_max_bytes", "")?),
        captions_enabled: flag("captions_enabled", "false")?,
        earcon_enabled: flag("earcon_enabled", "false")?,
        ducking_enabled: flag("ducking_enabled", "false")?,
        input_interrupt_enabled: flag("input_interrupt_enabled", "true")?,
        input_interrupt_resume: if settings.get("input_interrupt_resume", "when_idle")? == "manual"
        {
            ResumePolicy::Manual
        } else {
            ResumePolicy::WhenIdle
        },
        captions_enabled_configured: settings.has("captions_enabled")?,
    })
}

/// The saved voice when the engine offers it, otherwise the engine's first voice.
///
/// # Errors
/// Returns the store error when a read fails.
pub(crate) fn speaking_voice(store: &Store, engine: &EngineView) -> aitts_store::Result<String> {
    let preferred = store.settings().get("voice", "")?;
    if engine.voices.contains(&preferred) {
        return Ok(preferred);
    }
    Ok(engine.voices.first().cloned().unwrap_or_default())
}

/// The configured cache ceiling, falling back to the default as Python does.
pub(crate) fn cache_limit(raw: &str) -> u64 {
    Bytes::parse(Value::Text(raw)).map_or(DEFAULT_CACHE_MAX_BYTES, |bytes| bytes.0)
}

fn languages(raw: &str) -> Vec<String> {
    let selected: Vec<&str> = raw.split(',').collect();
    if selected.iter().all(|code| LANGUAGE_CODES.contains(code)) {
        selected.into_iter().map(str::to_owned).collect()
    } else {
        vec!["en".to_owned()]
    }
}

fn playback_rate(raw: &str) -> f64 {
    raw.trim()
        .parse::<f64>()
        .ok()
        .and_then(|rate| PlaybackRate::parse(Value::Number(rate)).ok())
        .map_or(1.0, PlaybackRate::multiplier)
}
