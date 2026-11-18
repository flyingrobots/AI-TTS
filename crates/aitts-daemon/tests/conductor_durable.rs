// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-memory SQLite, one thread, no files).
//! Durability of conductor changes through `aitts-store`, with injected crashes.
//! Oracle: Python `Store.recover` (Synthesizing returns to Queued, Playing comes
//! back Paused) and the AI-TTS rule that a restart keeps playback held. A crash
//! must leave storage equal to the state before the failed call.
//! Fault matrix (crash = the ledger fails the call):
//! - record, before the write: every call of the workload, `crash_at_every_record_*`.
//! - recover, before the repair: `a_crash_before_the_repair_*`.
//! - recover, after the repair commits: `a_crash_after_the_repair_*`.
//! - Not covered: a torn write inside one record (the store commits each
//!   transition separately); a second crash during a retried recovery.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use aitts_daemon::conductor::durable::{Change, Durable, Ledger, LedgerError, StoreLedger};
use aitts_daemon::conductor::{Clip, Command, Outcome};
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

fn store() -> Store {
    Store::from_connection(Connection::open_in_memory().unwrap(), FixedClock).unwrap()
}

/// Fails the `fail_at`-th record call (counting from 0), or recover calls as asked.
struct Faulty<L> {
    inner: L,
    records: usize,
    fail_at: Option<usize>,
    recover_fault: Option<RecoverFault>,
}

#[derive(Clone, Copy)]
enum RecoverFault {
    BeforeRepair,
    AfterRepair,
}

impl<L: Ledger> Ledger for Faulty<L> {
    fn record(&mut self, changes: &[Change]) -> Result<(), LedgerError> {
        let call = self.records;
        self.records += 1;
        if self.fail_at == Some(call) {
            return Err(LedgerError::Unavailable);
        }
        self.inner.record(changes)
    }

    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        match self.recover_fault.take() {
            Some(RecoverFault::BeforeRepair) => Err(LedgerError::Unavailable),
            Some(RecoverFault::AfterRepair) => {
                self.inner.recover().and(Err(LedgerError::Unavailable))
            }
            None => self.inner.recover(),
        }
    }
}

fn faulty(store: &Store, fail_at: Option<usize>) -> Faulty<StoreLedger<'_>> {
    Faulty {
        inner: StoreLedger::new(store),
        records: 0,
        fail_at,
        recover_fault: None,
    }
}

/// Store the utterance as the API would, then submit it to the conductor.
fn submit<L: Ledger>(store: &Store, durable: &mut Durable<L>, id: &str, priority: Priority) {
    let mut new = NewUtterance::new(id.to_owned(), "text".to_owned(), "voice".to_owned(), 1.0);
    new.priority = match priority {
        Priority::Normal => aitts_store::Priority::Normal,
        Priority::Urgent => aitts_store::Priority::Urgent,
        Priority::Preempt => aitts_store::Priority::Preempt,
    };
    new.at_head = priority != Priority::Normal;
    store.queue().submit(&new).unwrap();
    let command = Command::Submit {
        id: id.to_owned(),
        priority,
        playback: Playback::Play,
    };
    assert_eq!(durable.apply(command).unwrap(), Outcome::Applied);
}

/// What recovery should leave from an in-memory state.
fn after_recovery(clips: &[Clip]) -> Vec<(String, State, f64)> {
    let mut expected: Vec<_> = clips
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
    expected.sort_by(|left, right| left.2.total_cmp(&right.2));
    expected
}

fn recovered(store: &Store) -> (Vec<(String, State, f64)>, bool) {
    let durable = Durable::recover(StoreLedger::new(store)).unwrap();
    let clips = durable.conductor().clips();
    let rows = clips
        .into_iter()
        .map(|clip| (clip.id, clip.state, clip.order))
        .collect();
    (rows, durable.conductor().held())
}

type Step<L> = fn(&Store, &mut Durable<L>) -> Result<(), ()>;

fn ok<T, E>(result: Result<T, E>) -> Result<(), ()> {
    result.map(|_| ()).map_err(|_| ())
}

/// Recovered empty, then a workload with synthesis, failure, playback, reorder, preemption and clear.
fn workload<L: Ledger>() -> Vec<Step<L>> {
    vec![
        // A recovered queue starts held; the listener releases it.
        |_, durable| ok(durable.apply(Command::Resume)),
        |store, durable| {
            submit(store, durable, "a", Priority::Normal);
            submit(store, durable, "b", Priority::Normal);
            submit(store, durable, "c", Priority::Normal);
            Ok(())
        },
        |_, durable| ok(durable.next_synthesis()),
        |_, durable| ok(durable.apply(Command::AudioReady("a".to_owned()))),
        |_, durable| ok(durable.plan_playback()),
        |_, durable| ok(durable.apply(Command::Reorder(vec!["c".to_owned(), "b".to_owned()]))),
        |_, durable| ok(durable.next_synthesis()),
        |_, durable| ok(durable.apply(Command::SynthesisFailed("c".to_owned()))),
        |store, durable| {
            submit(store, durable, "alert", Priority::Preempt);
            Ok(())
        },
        |_, durable| ok(durable.next_synthesis()),
        |_, durable| ok(durable.apply(Command::AudioReady("alert".to_owned()))),
        |_, durable| ok(durable.plan_playback()),
        |_, durable| ok(durable.apply(Command::Cancel("b".to_owned()))),
        |_, durable| ok(durable.apply(Command::ClearQueue)),
    ]
}

#[test]
fn a_restart_restores_the_queue_with_playback_held() {
    let store = store();
    let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
    for step in workload().into_iter().take(12) {
        step(&store, &mut durable).unwrap();
    }
    let expected = after_recovery(&durable.conductor().clips());
    assert_eq!(recovered(&store), (expected, true));
}

#[test]
fn a_failed_record_leaves_memory_unchanged() {
    let store = store();
    let mut durable = Durable::recover(faulty(&store, Some(0))).unwrap();
    submit(&store, &mut durable, "a", Priority::Normal);
    let before = durable.conductor().clips();
    assert!(
        durable.next_synthesis().is_err(),
        "the injected record fault was not reported"
    );
    assert_eq!(durable.conductor().clips(), before);
}

#[test]
fn crash_at_every_record_leaves_the_state_before_the_failed_call() {
    let mut crashes = 0;
    // Bounded: a ledger that fails every call would otherwise never finish.
    for fail_at in 0..64 {
        let store = store();
        let mut durable = Durable::recover(faulty(&store, Some(fail_at))).unwrap();
        let mut failure = None;
        for (index, step) in workload().into_iter().enumerate() {
            let before = durable.conductor().clips();
            if step(&store, &mut durable).is_err() {
                failure = Some((index, before));
                break;
            }
        }
        let Some((index, before)) = failure else {
            break;
        };
        crashes += 1;
        drop(durable);
        let expected = (after_recovery(&before), true);
        assert_eq!(
            recovered(&store),
            expected,
            "fail_at={fail_at}, workload step {index}"
        );
    }
    // Witness count: one crash per state-changing call; zero means no fault fired.
    assert_eq!(crashes, 11, "crashes injected");
}

fn recovery_retry_converges(fault: RecoverFault) {
    let store = store();
    let mut durable = Durable::recover(StoreLedger::new(&store)).unwrap();
    for step in workload().into_iter().take(12) {
        step(&store, &mut durable).unwrap();
    }
    let expected = (after_recovery(&durable.conductor().clips()), true);
    let mut ledger = faulty(&store, None);
    ledger.recover_fault = Some(fault);
    assert!(
        Durable::recover(ledger).is_err(),
        "the injected recovery fault was not reported"
    );
    assert_eq!(recovered(&store), expected);
}

#[test]
fn a_crash_before_the_repair_is_recovered_by_the_next_start() {
    recovery_retry_converges(RecoverFault::BeforeRepair);
}

#[test]
fn a_crash_after_the_repair_is_recovered_by_the_next_start() {
    recovery_retry_converges(RecoverFault::AfterRepair);
}
