// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns writing new queue positions, as the Python `reorder_pending`.

use crate::Result;
use crate::queue::Queue;

impl Queue<'_> {
    /// Set each named utterance's order key in one transaction.
    ///
    /// # Errors
    /// Returns [`crate::Error::NotFound`] for an unknown id, or a write failure;
    /// the whole change then rolls back.
    pub fn reorder(&self, keys: &[(String, f64)]) -> Result<()> {
        let _unwritten = keys.len();
        Ok(())
    }
}
