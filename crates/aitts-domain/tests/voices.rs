// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: `voice_assignment.py` precedence and `voice_languages.py` prefix table.

use aitts_domain::voices::{
    Claim, EmptyCatalog, VoiceDecision, VoiceRequest, automatic_pool, decide, is_agent_source,
    language,
};

fn request() -> VoiceRequest<'static> {
    VoiceRequest {
        source: Some("client"),
        requested: None,
        default_voice: "default",
        catalog: &["a", "b"],
        pinned: None,
        claimed: None,
        taken: &[],
    }
}

fn assert_decision(request: VoiceRequest<'_>, voice: &str, claim: Claim) {
    assert_eq!(
        decide(request),
        Ok(VoiceDecision { voice, claim }),
        "{request:?}"
    );
}

#[test]
fn listener_override_and_ui_requests_preserve_claims() {
    let base = request();
    assert_decision(
        VoiceRequest {
            pinned: Some("pin"),
            requested: Some("b"),
            ..base
        },
        "pin",
        Claim::Preserve,
    );
    assert_decision(
        VoiceRequest {
            source: Some("macos-service"),
            ..base
        },
        "default",
        Claim::Preserve,
    );
    assert_decision(
        VoiceRequest {
            source: None,
            requested: Some("b"),
            ..base
        },
        "b",
        Claim::Preserve,
    );
}

#[test]
fn available_requests_claims_and_other_client_conflicts_follow_precedence() {
    let base = request();
    assert_decision(
        VoiceRequest {
            claimed: Some("a"),
            requested: Some("a"),
            ..base
        },
        "a",
        Claim::Preserve,
    );
    assert_decision(
        VoiceRequest {
            claimed: Some("a"),
            requested: Some("b"),
            ..base
        },
        "b",
        Claim::Acquire,
    );
    assert_decision(
        VoiceRequest {
            claimed: Some("a"),
            requested: Some("b"),
            taken: &["b"],
            ..base
        },
        "a",
        Claim::Preserve,
    );
    assert_decision(
        VoiceRequest {
            requested: Some("a"),
            taken: &["a"],
            ..base
        },
        "b",
        Claim::Acquire,
    );
    assert_decision(
        VoiceRequest {
            claimed: Some("b"),
            ..base
        },
        "b",
        Claim::Preserve,
    );
}

#[test]
fn automatic_allocation_follows_catalog_order_and_shares_on_exhaustion() {
    let base = request();
    assert_decision(base, "a", Claim::Acquire);
    assert_decision(
        VoiceRequest {
            taken: &["a", "b"],
            ..base
        },
        "a",
        Claim::Acquire,
    );
    assert_eq!(
        decide(VoiceRequest {
            catalog: &[],
            ..base
        }),
        Err(EmptyCatalog)
    );
}

#[test]
fn client_classification_and_language_pool_preserve_python_rules() {
    for (source, expected) in [
        (None, false),
        (Some("  "), false),
        (Some("menubar-preview"), false),
        (Some("macos-service"), false),
        (Some("Macos-agent"), true),
        (Some("agent"), true),
    ] {
        assert_eq!(is_agent_source(source), expected, "{source:?}");
    }
    for (voice, expected) in [
        ("af_heart", "en"),
        ("bm_george", "en"),
        ("ef_dora", "es"),
        ("ff_siwis", "fr"),
        ("hf_alpha", "hi"),
        ("if_sara", "it"),
        ("pf_dora", "pt"),
        ("jf_alpha", "ja"),
        ("zf_xiaobei", "zh"),
        ("af_", "other"),
        ("amXx", "other"),
        ("🦀f_name", "other"),
    ] {
        assert_eq!(language(voice), expected, "{voice}");
    }
    assert_eq!(
        automatic_pool(&["zf_a", "af_b", "ef_c", "af_d", "unknown"], &["en", "es"]).unwrap(),
        ["af_b", "ef_c", "af_d"]
    );
    assert_eq!(
        automatic_pool(&["alice", "bob"], &["en"]).unwrap(),
        ["alice", "bob"]
    );
    assert_eq!(
        automatic_pool(&["af_a"], &["zh"]).unwrap(),
        Vec::<&str>::new()
    );
}
