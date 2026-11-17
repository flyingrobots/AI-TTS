// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small. Oracle: public per-snapshot allocation admission, before copying entries.
#![allow(clippy::unwrap_used, reason = "test code fails loudly")]
use aitts_domain::{
    CollectionLimit, MAX_COLLECTION_ENTRIES,
    plan::{Entry, OrderKey, Playback, Priority, UtteranceId, ordered},
    retention::{AccessTimeNs, Artifact, InvalidInventory, Protection, eviction},
    settings::{Bytes, InvalidSetting, languages},
    utterance::State,
    voices::automatic_pool,
};

fn over_limit() -> CollectionLimit {
    CollectionLimit {
        observed: 65_537,
        maximum: 65_536,
    }
}

#[test]
fn queue_snapshot_allocation_has_an_inclusive_entry_limit() {
    assert_eq!(MAX_COLLECTION_ENTRIES, 65_536);
    let mut entries = vec![
        Entry {
            id: UtteranceId("same"),
            order: OrderKey::new(0.0).unwrap(),
            priority: Priority::Normal,
            state: State::Ready,
            playback: Playback::Play
        };
        65_536
    ];
    assert_eq!(ordered(&entries).unwrap(), entries);
    entries.push(*entries.first().unwrap());
    assert_eq!(ordered(&entries).unwrap_err(), over_limit());
}

#[test]
fn voice_catalog_admission_propagates_to_language_settings() {
    let mut catalog = vec!["af_example"; 65_536];
    assert_eq!(automatic_pool(&catalog, &["en"]).unwrap(), catalog);
    assert_eq!(languages(&["en"], &catalog).unwrap(), ["en"]);
    catalog.push("af_example");
    assert_eq!(automatic_pool(&catalog, &["en"]).unwrap_err(), over_limit());
    assert_eq!(
        languages(&["en"], &catalog),
        Err(InvalidSetting::Collection(over_limit()))
    );
}

#[test]
fn artifact_inventory_refuses_over_limit_before_duplicate_validation() {
    let ids: Vec<_> = (0..65_536).map(|n| n.to_string()).collect();
    let mut artifacts: Vec<_> = ids
        .iter()
        .map(|id| Artifact {
            id,
            bytes: Bytes(1),
            accessed: AccessTimeNs(0),
            protection: Protection::Unprotected,
        })
        .collect();
    let accepted = eviction(&artifacts, Bytes(65_536)).unwrap();
    assert_eq!(accepted.before, Bytes(65_536));
    assert_eq!(accepted.candidates, Vec::<&str>::new());
    artifacts.push(*artifacts.first().unwrap());
    assert_eq!(
        eviction(&artifacts, Bytes(65_536)),
        Err(InvalidInventory::Collection(over_limit()))
    );
}
