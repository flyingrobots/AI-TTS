// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns deterministic cache eviction proposals from an inventory.
//! Callers perform deletion and re-plan after failed or concurrent changes.

#![deny(clippy::arithmetic_side_effects)]

use crate::settings::Bytes;
use alloc::vec::Vec;
use core::fmt;

/// Nanoseconds in the caller's consistent access-time coordinate system.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct AccessTimeNs(pub i64);

/// Whether an artifact must remain available to an active or resumable utterance.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Protection {
    /// May be evicted.
    Unprotected,
    /// Must be retained.
    Protected,
}

/// An observed cache artifact. Identifiers must be unique within an inventory.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Artifact<'a> {
    /// Stable identity, also used to break equal-access-time ties.
    pub id: &'a str,
    /// Observed size.
    pub bytes: Bytes,
    /// Last observed access time.
    pub accessed: AccessTimeNs,
    /// Protection supplied by the caller's active references.
    pub protection: Protection,
}

/// An inventory cannot be accounted for safely.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InvalidInventory {
    /// The total size does not fit a `u64` byte count.
    SizeOverflow,
    /// Two observations use the same identity.
    DuplicateId,
}
impl fmt::Display for InvalidInventory {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid cache inventory: {self:?}")
    }
}
impl core::error::Error for InvalidInventory {}

/// A proposal assuming each selected deletion succeeds.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Eviction<'a> {
    /// Delete in this order, oldest access first and identity as a tie-breaker.
    pub candidates: Vec<&'a str>,
    /// Observed total before deletion.
    pub before: Bytes,
    /// Expected total after all selected deletions succeed.
    pub projected: Bytes,
    /// Bytes above the requested limit that protected artifacts prevent removing.
    pub unmet: Bytes,
}

/// Select the minimum LRU prefix needed to reach the limit, excluding protected artifacts.
/// A zero limit asks to remove all removable bytes; this is not a purge operation.
///
/// # Errors
/// Returns `InvalidInventory` for duplicate identities or an overflowing total.
pub fn eviction<'a>(
    inventory: &[Artifact<'a>],
    limit: Bytes,
) -> Result<Eviction<'a>, InvalidInventory> {
    let mut ids: Vec<_> = inventory.iter().map(|entry| entry.id).collect();
    ids.sort_unstable();
    if ids.windows(2).any(|pair| pair.first() == pair.last()) {
        return Err(InvalidInventory::DuplicateId);
    }
    let before = inventory.iter().try_fold(0_u64, |sum, entry| {
        sum.checked_add(entry.bytes.0)
            .ok_or(InvalidInventory::SizeOverflow)
    })?;
    let mut eligible: Vec<_> = inventory
        .iter()
        .filter(|entry| entry.protection == Protection::Unprotected)
        .collect();
    eligible.sort_by_key(|entry| (entry.accessed, entry.id));
    let mut projected = before;
    let mut candidates = Vec::new();
    for entry in eligible {
        if projected <= limit.0 {
            break;
        }
        projected = projected
            .checked_sub(entry.bytes.0)
            .ok_or(InvalidInventory::SizeOverflow)?;
        candidates.push(entry.id);
    }
    Ok(Eviction {
        candidates,
        before: Bytes(before),
        projected: Bytes(projected),
        unmet: Bytes(projected.saturating_sub(limit.0)),
    })
}
