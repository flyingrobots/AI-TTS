// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files). Oracle: architecture §4: one transition is one
//! transaction, so a fault leaves the parent and every child as they were.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

mod support;

use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{Error, State, Store};
use rusqlite::Connection;
use support::FixedClock;

#[test]
fn a_fault_inside_a_terminal_transition_leaves_no_half_written_state() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    let store = Store::open(&path, FixedClock(5.0)).unwrap();
    let mut doc = NewUtterance::new("utt_doc".to_owned(), "doc".to_owned(), "v".to_owned(), 1.0);
    doc.segments = Some(vec!["one".to_owned(), "two".to_owned()]);
    store.queue().submit(&doc).unwrap();
    store.close().unwrap();

    // The parent update succeeds; the cascading child cancellation then faults.
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        "CREATE TRIGGER fault BEFORE UPDATE OF state ON utterance_segments \
         BEGIN SELECT RAISE(ABORT, 'seeded fault'); END;",
    )
    .unwrap();
    let store = Store::from_connection(db, FixedClock(9.0)).unwrap();
    let queue = store.queue();

    let result = queue.transition("utt_doc", State::Cancelled, &Fields::default());

    assert!(matches!(result, Err(Error::Sqlite(_))), "{result:?}");
    let parent = queue.get("utt_doc").unwrap().unwrap();
    let children: Vec<State> = queue
        .segments("utt_doc")
        .unwrap()
        .iter()
        .map(|s| s.state)
        .collect();
    assert_eq!(
        (parent.state, parent.state_changed_at, children),
        (State::Queued, 5.0, vec![State::Queued, State::Queued])
    );
}
