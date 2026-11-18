// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-memory SQLite, one thread).
//! Submission through the store: the conductor takes the order key the store
//! assigned, so the two agree after a restart that loads no history.
//! Oracle: Python `Store.submit` (normal work goes after every row, history
//! included, as `MAX(order_key) + 1`; urgent work before unfinished work), read
//! back from the store rows themselves, and the restart rule that playback is held.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use aitts_daemon::conductor::durable::{Durable, DurableError, StoreLedger};
use aitts_daemon::conductor::{Command, Outcome, Refusal};
use aitts_domain::utterance::State;
use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{Clock, Priority, Store};
use rusqlite::Connection;

struct FixedClock;
impl Clock for FixedClock {
    fn now(&self) -> f64 {
        1_000.0
    }
}

fn store() -> Store {
    Store::from_connection(Connection::open_in_memory().unwrap(), FixedClock).unwrap()
}

fn new(id: &str, priority: Priority) -> NewUtterance {
    let mut new = NewUtterance::new(id.to_owned(), "text".to_owned(), "voice".to_owned(), 1.0);
    new.priority = priority;
    new.at_head = priority != Priority::Normal;
    new
}

type Keys = Vec<(String, f64)>;

/// Conductor clips and store rows, each as (id, order key), in queue order.
fn keys(durable: &Durable<StoreLedger<'_>>, store: &Store) -> (Keys, Keys) {
    let conductor = durable
        .conductor()
        .clips()
        .into_iter()
        .map(|clip| (clip.id, clip.order))
        .collect();
    let mut rows = store.queue().input().unwrap();
    rows.extend(store.queue().playback().unwrap());
    rows.sort_by(|left, right| left.order_key.total_cmp(&right.order_key));
    (
        conductor,
        rows.into_iter()
            .map(|row| (row.id, row.order_key))
            .collect(),
    )
}

#[test]
fn a_submission_after_a_restart_takes_the_store_key_after_history() {
    let store = store();
    // History the restarted conductor does not load: one played utterance.
    store.queue().submit(&new("old", Priority::Normal)).unwrap();
    for to in [
        State::Synthesizing,
        State::Ready,
        State::Playing,
        State::Played,
    ] {
        store
            .queue()
            .transition("old", to, &Fields::default())
            .unwrap();
    }
    let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
    assert_eq!(
        durable.submit(&new("next", Priority::Normal)).unwrap(),
        Outcome::Applied
    );
    let (conductor, rows) = keys(&durable, &store);
    assert_eq!(
        conductor, rows,
        "conductor and store disagree on queue keys"
    );
}

#[test]
fn a_restart_with_queued_work_keeps_keys_and_holds_playback() {
    let store = store();
    let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
    durable.apply(Command::Resume).unwrap();
    for (id, priority) in [
        ("a", Priority::Normal),
        ("b", Priority::Normal),
        ("u", Priority::Urgent),
    ] {
        durable.submit(&new(id, priority)).unwrap();
    }
    assert_eq!(durable.next_synthesis().unwrap().as_deref(), Some("u"));
    let before = keys(&durable, &store).0;
    drop(durable);
    let restored = Durable::recover(StoreLedger::new(&store)).unwrap();
    assert!(restored.conductor().held(), "a restart must hold playback");
    assert_eq!(keys(&restored, &store), (before.clone(), before));
}

#[test]
fn a_duplicate_submission_is_refused_and_stores_nothing() {
    let store = store();
    let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
    durable.submit(&new("a", Priority::Normal)).unwrap();
    let mut again = new("a", Priority::Normal);
    again.text = "changed".to_owned();
    let refused = durable.submit(&again);
    assert!(
        matches!(refused, Err(DurableError::Refused(Refusal::Duplicate(ref id))) if id == "a"),
        "got {refused:?}"
    );
    assert_eq!(
        store.queue().get("a").unwrap().unwrap().text,
        "text",
        "the duplicate changed the stored row"
    );
}
