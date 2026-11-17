// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small. Oracle: application/cache.py LRU/identity order and protected-reference contract.

use aitts_domain::retention::{
    AccessTimeNs, Artifact, Eviction, InvalidInventory, Protection, eviction,
};
use aitts_domain::settings::Bytes;

#[test]
fn lru_ties_protection_and_unreachable_limits_produce_honest_proposals() {
    let artifact = |id, bytes, accessed, protection| Artifact {
        id,
        bytes: Bytes(bytes),
        accessed: AccessTimeNs(accessed),
        protection,
    };
    let inventory = [
        artifact("b", 5, 1, Protection::Unprotected),
        artifact("held", 7, -10, Protection::Protected),
        artifact("new", 10, 9, Protection::Unprotected),
        artifact("a", 3, 1, Protection::Unprotected),
    ];
    assert_eq!(
        eviction(&inventory, Bytes(20)),
        Ok(Eviction {
            candidates: vec!["a", "b"],
            before: Bytes(25),
            projected: Bytes(17),
            unmet: Bytes(0)
        })
    );
    assert_eq!(
        eviction(&inventory, Bytes(5)),
        Ok(Eviction {
            candidates: vec!["a", "b", "new"],
            before: Bytes(25),
            projected: Bytes(7),
            unmet: Bytes(2)
        })
    );
    assert_eq!(
        eviction(&inventory, Bytes(25)),
        Ok(Eviction {
            candidates: vec![],
            before: Bytes(25),
            projected: Bytes(25),
            unmet: Bytes(0)
        })
    );
    assert_eq!(
        eviction(&[], Bytes(0)),
        Ok(Eviction {
            candidates: vec![],
            before: Bytes(0),
            projected: Bytes(0),
            unmet: Bytes(0)
        })
    );
}

#[test]
fn duplicate_identity_and_total_overflow_are_refused() {
    let entry = Artifact {
        id: "a",
        bytes: Bytes(u64::MAX),
        accessed: AccessTimeNs(0),
        protection: Protection::Unprotected,
    };
    assert_eq!(
        eviction(&[entry, entry], Bytes(0)),
        Err(InvalidInventory::DuplicateId)
    );
    assert_eq!(
        eviction(
            &[
                entry,
                Artifact {
                    id: "b",
                    bytes: Bytes(1),
                    ..entry
                }
            ],
            Bytes(0)
        ),
        Err(InvalidInventory::SizeOverflow)
    );
}
