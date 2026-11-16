// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns voice claim precedence and automatic language pools.

use alloc::vec::Vec;
use core::fmt;

/// A claim change that the caller may persist after accepting a submission.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Claim {
    /// Preserve the current registry.
    Preserve,
    /// Claim the selected voice for this client.
    Acquire,
}

/// The selected voice and the corresponding registry decision.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct VoiceDecision<'a> {
    /// Voice identifier supplied by the caller's catalog or override.
    pub voice: &'a str,
    /// Whether this selection creates a client claim.
    pub claim: Claim,
}

/// A snapshot of the registry after stale claims and catalog validation.
///
/// The caller must exclude this client's own claim from `taken`, validate a
/// requested voice against the engine catalog, and apply language restrictions.
#[derive(Clone, Copy, Debug)]
pub struct VoiceRequest<'a> {
    /// Client identity, or a listener-originated request.
    pub source: Option<&'a str>,
    /// Validated explicit selection.
    pub requested: Option<&'a str>,
    /// Engine fallback for listener requests.
    pub default_voice: &'a str,
    /// Eligible automatic voices in engine order.
    pub catalog: &'a [&'a str],
    /// Listener override, which takes precedence over client input.
    pub pinned: Option<&'a str>,
    /// This client's current claim.
    pub claimed: Option<&'a str>,
    /// Voices held by other clients.
    pub taken: &'a [&'a str],
}

/// No automatic voice can be selected from an empty catalog.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EmptyCatalog;

impl fmt::Display for EmptyCatalog {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("voice catalog is empty")
    }
}

impl core::error::Error for EmptyCatalog {}

/// Whether this source should hold a distinct client voice.
pub fn is_agent_source(source: Option<&str>) -> bool {
    source.is_some_and(|name| {
        !name.trim().is_empty() && !name.starts_with("macos-") && !name.starts_with("menubar-")
    })
}

/// Resolve pinned, requested, claimed, and unclaimed voices in that order.
///
/// # Errors
/// Returns `EmptyCatalog` when automatic allocation needs an empty catalog.
pub fn decide(request: VoiceRequest<'_>) -> Result<VoiceDecision<'_>, EmptyCatalog> {
    let preserve = |voice| VoiceDecision {
        voice,
        claim: Claim::Preserve,
    };
    if let Some(pinned) = request.pinned {
        return Ok(preserve(pinned));
    }
    if !is_agent_source(request.source) {
        return Ok(preserve(
            request
                .requested
                .filter(|voice| !voice.is_empty())
                .unwrap_or(request.default_voice),
        ));
    }
    if let Some(requested) = request.requested {
        if Some(requested) == request.claimed {
            return Ok(preserve(requested));
        }
        if !request.taken.contains(&requested) {
            return Ok(VoiceDecision {
                voice: requested,
                claim: Claim::Acquire,
            });
        }
    }
    if let Some(claimed) = request.claimed {
        return Ok(preserve(claimed));
    }
    let voice = request
        .catalog
        .iter()
        .copied()
        .find(|voice| !request.taken.contains(voice))
        .or_else(|| request.catalog.first().copied())
        .ok_or(EmptyCatalog)?;
    Ok(VoiceDecision {
        voice,
        claim: Claim::Acquire,
    })
}

/// Supported automatic-selection language codes, in canonical settings order.
pub const LANGUAGE_CODES: [&str; 9] = ["en", "es", "fr", "hi", "it", "pt", "ja", "zh", "other"];

/// Read Kokoro's voice prefix; unrecognized catalogs have `other` metadata.
pub fn language(voice: &str) -> &'static str {
    let mut chars = voice.chars();
    let prefix = chars.next();
    if !matches!(chars.next(), Some('f' | 'm'))
        || chars.next() != Some('_')
        || chars.next().is_none()
    {
        return "other";
    }
    match prefix {
        Some('a' | 'b') => "en",
        Some('e') => "es",
        Some('f') => "fr",
        Some('h') => "hi",
        Some('i') => "it",
        Some('p') => "pt",
        Some('j') => "ja",
        Some('z') => "zh",
        _ => "other",
    }
}

/// Filter a metadata-aware catalog, preserving order. Unknown catalogs pass through.
pub fn automatic_pool<'a>(catalog: &[&'a str], languages: &[&str]) -> Vec<&'a str> {
    if catalog.iter().all(|voice| language(voice) == "other") {
        return catalog.to_vec();
    }
    catalog
        .iter()
        .copied()
        .filter(|voice| languages.contains(&language(voice)))
        .collect()
}
