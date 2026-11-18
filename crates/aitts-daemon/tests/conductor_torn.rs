// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (a temporary SQLite file shared by two connections).
//! Crashes between the individual row writes of one save, and during recovery.
//! Injection: a SQLite trigger aborts the Nth `UPDATE utterances`, for every N,
//! inside the store's own statements. The trigger is then dropped, as a restart
//! with healthy storage would see it.
//! Oracles: a save is all-or-nothing, so storage after a crash equals the state
//! before the failed call with Python `Store.recover` applied (Synthesizing to
//! Queued, Playing to Paused), held. Recovery after a crash during recovery gives
//! the same restored, held state as one clean recovery.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use std::path::Path;

use aitts_daemon::conductor::durable::{Durable, StoreLedger};
use aitts_daemon::conductor::{Clip, Command};
use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;
use aitts_store::queue::NewUtterance;
use aitts_store::{Clock, Store};
use rusqlite::Connection;

struct FixedClock;
impl Clock for FixedClock {
    fn now(&self) -> f64 {
        1_000.0
    }
}

type Rows = Vec<(String, State, f64)>;
type Ledgered<'a> = Durable<StoreLedger<'a>>;

/// Abort the update after `allowed` successful ones.
fn arm(path: &Path, allowed: u32) {
    let db = Connection::open(path).unwrap();
    db.execute_batch(&format!(
        "CREATE TABLE fault(n INTEGER); INSERT INTO fault VALUES ({allowed});
         CREATE TRIGGER crash BEFORE UPDATE ON utterances BEGIN
           SELECT RAISE(ABORT, 'injected crash') WHERE (SELECT n FROM fault) <= 0;
           UPDATE fault SET n = n - 1;
         END;"
    ))
    .unwrap();
}

fn disarm(path: &Path) {
    let db = Connection::open(path).unwrap();
    db.execute_batch("DROP TRIGGER IF EXISTS crash; DROP TABLE IF EXISTS fault;")
        .unwrap();
}

fn submit(store: &Store, durable: &mut Ledgered<'_>, id: &str, priority: Priority) {
    let mut new = NewUtterance::new(id.to_owned(), "text".to_owned(), "voice".to_owned(), 1.0);
    if priority == Priority::Preempt {
        new.priority = aitts_store::Priority::Preempt;
        new.at_head = true;
    }
    store.queue().submit(&new).unwrap();
    let command = Command::Submit {
        id: id.to_owned(),
        priority,
        playback: Playback::Play,
    };
    durable.apply(command).unwrap();
}

/// Each step returns whether its save succeeded.
fn workload() -> Vec<fn(&Store, &mut Ledgered<'_>) -> bool> {
    vec![
        |_, d| d.apply(Command::Resume).is_ok(),
        |s, d| {
            submit(s, d, "a", Priority::Normal);
            submit(s, d, "b", Priority::Normal);
            submit(s, d, "c", Priority::Normal);
            true
        },
        |_, d| d.next_synthesis().is_ok(),
        |_, d| d.apply(Command::AudioReady("a".to_owned())).is_ok(),
        |_, d| d.plan_playback().is_ok(),
        // Two order writes in one save.
        |_, d| {
            d.apply(Command::Reorder(vec!["c".to_owned(), "b".to_owned()]))
                .is_ok()
        },
        |s, d| {
            submit(s, d, "alert", Priority::Preempt);
            true
        },
        |_, d| d.next_synthesis().is_ok(),
        |_, d| d.apply(Command::AudioReady("alert".to_owned())).is_ok(),
        // Two transitions in one save: suspend "a", start "alert".
        |_, d| d.plan_playback().is_ok(),
        // Three writes in one save: skip "a", cancel "b" and "c".
        |_, d| d.apply(Command::ClearQueue).is_ok(),
    ]
}

fn after_recovery(clips: &[Clip]) -> Rows {
    let mut rows: Rows = clips
        .iter()
        .filter(|clip| !clip.state.is_terminal())
        .map(|clip| {
            let state = match clip.state {
                State::Synthesizing => State::Queued,
                State::Playing => State::Paused,
                other => other,
            };
            (clip.id.clone(), state, clip.order)
        })
        .collect();
    rows.sort_by(|left, right| left.2.total_cmp(&right.2));
    rows
}

fn recovered(store: &Store) -> (Rows, bool) {
    let durable = Durable::recover(StoreLedger::new(store)).unwrap();
    let rows = durable.conductor().clips().into_iter();
    (
        rows.map(|clip| (clip.id, clip.state, clip.order)).collect(),
        durable.conductor().held(),
    )
}

#[test]
fn a_crash_between_the_row_writes_of_one_save_leaves_all_or_nothing() {
    let mut crashes = 0;
    for allowed in 0..64 {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("state.db");
        let store = Store::open(&path, FixedClock).unwrap();
        let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
        arm(&path, allowed);
        let mut failure = None;
        for (index, step) in workload().into_iter().enumerate() {
            let before = durable.conductor().clips();
            if !step(&store, &mut durable) {
                failure = Some((index, before));
                break;
            }
        }
        let Some((index, before)) = failure else {
            break;
        };
        crashes += 1;
        drop(durable);
        disarm(&path);
        let expected = (after_recovery(&before), true);
        assert_eq!(
            recovered(&store),
            expected,
            "crash after {allowed} row writes, step {index}"
        );
    }
    // Witness count: one crash per row write the workload makes
    // (synthesis 1, ready 1, start 1, reorder 2, synthesis 1, ready 1, preempt 2, clear 3).
    assert_eq!(crashes, 12, "row-write crashes injected");
}

#[test]
fn a_crash_during_recovery_is_repaired_by_the_next_recovery() {
    let mut crashes = 0;
    for allowed in 0..64 {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("state.db");
        let store = Store::open(&path, FixedClock).unwrap();
        let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
        for step in workload().into_iter().take(10) {
            assert!(
                step(&store, &mut durable),
                "workload save failed without a fault"
            );
        }
        // Leave one clip synthesizing as well as one playing: recovery writes both.
        assert_eq!(durable.next_synthesis().unwrap().as_deref(), Some("c"));
        let expected = (after_recovery(&durable.conductor().clips()), true);
        drop(durable);
        arm(&path, allowed);
        if Durable::recover(StoreLedger::new(&store)).is_ok() {
            break;
        }
        crashes += 1;
        disarm(&path);
        assert_eq!(
            recovered(&store),
            expected,
            "crash after {allowed} recovery writes"
        );
    }
    // Witness count: one crash per recovery write (Synthesizing to Queued, Playing to Paused).
    assert_eq!(crashes, 2, "recovery crashes injected");
}
