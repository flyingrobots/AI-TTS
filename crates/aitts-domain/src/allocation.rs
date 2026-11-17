// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Admission for vectors copied from caller-owned snapshots.
use core::fmt;

/// Maximum entries copied from a queue, voice catalog, or artifact inventory.
/// Borrowed strings are not copied. Callers must partition larger snapshots.
pub const MAX_COLLECTION_ENTRIES: usize = 65_536;

/// An input snapshot would allocate more entries than the domain allowance.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CollectionLimit {
    /// Number of entries supplied by the caller.
    pub observed: usize,
    /// Maximum admitted entries.
    pub maximum: usize,
}
impl fmt::Display for CollectionLimit {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "collection has {} entries; maximum {}",
            self.observed, self.maximum
        )
    }
}
impl core::error::Error for CollectionLimit {}

pub(crate) fn admit(observed: usize) -> Result<(), CollectionLimit> {
    if observed > MAX_COLLECTION_ENTRIES {
        return Err(CollectionLimit {
            observed,
            maximum: MAX_COLLECTION_ENTRIES,
        });
    }
    Ok(())
}
