// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files). Oracle: Python `Store.counts`, which groups
//! every utterance row by its stored state and omits states with no rows.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

mod support;

use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{State, Store};
use support::FixedClock;

fn submit(store: &Store, id: &str) {
    let new = NewUtterance::new(id.to_owned(), "text".to_owned(), "v".to_owned(), 1.0);
    store.queue().submit(&new).unwrap();
}

#[test]
fn counts_group_every_row_by_state_and_omit_empty_states() {
    let dir = tempfile::tempdir().unwrap();
    let store = Store::open(&dir.path().join("state.db"), FixedClock(5.0)).unwrap();
    submit(&store, "utt_a");
    submit(&store, "utt_b");
    submit(&store, "utt_c");
    store
        .queue()
        .transition("utt_c", State::Cancelled, &Fields::default())
        .unwrap();

    let counts = store.counts().unwrap();

    assert_eq!(counts, vec![(State::Queued, 2), (State::Cancelled, 1)]);
}
