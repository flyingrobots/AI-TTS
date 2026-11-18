// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (pure state, one thread).
//! The events a durable conductor produces for its recorded changes.
//! Oracle: Python `PlaybackController._suspend_current` and `_start_saved`
//! (the current speaker is suspended before the interrupting clip starts),
//! `clear_preempted` before `clear_pending` (skips before cancels), and
//! `Store.transition`'s `on_transition` callbacks, one per transition.

#![allow(clippy::unwrap_used, clippy::panic, reason = "test code fails loudly")]

use aitts_daemon::conductor::durable::{Change, Durable, Ledger, LedgerError};
use aitts_daemon::conductor::{Clip, Command};
use aitts_domain::plan::{Playback, Priority};
use aitts_protocol::event::Event;
use aitts_protocol::value::Nullable;
use aitts_protocol::vocabulary::State;

/// Records nothing, stamps 7.0, and fails while `refusing`.
#[derive(Default)]
struct Stamping {
    refusing: bool,
}
impl Ledger for Stamping {
    fn record(&mut self, _changes: &[Change]) -> Result<(), LedgerError> {
        if self.refusing {
            Err(LedgerError::Unavailable)
        } else {
            Ok(())
        }
    }
    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        Ok(Vec::new())
    }
    fn stamp(&self) -> f64 {
        7.0
    }
}

fn changed(id: &str, from: State, to: State) -> (String, State, State) {
    (id.to_owned(), from, to)
}

/// The state changes among `events`, as (id, from, to).
fn transitions(events: &[Event]) -> Vec<(String, State, State)> {
    events
        .iter()
        .map(|event| match event {
            Event::StateChanged {
                id,
                from: Nullable::Value(from),
                to,
                at,
            } => {
                assert_eq!(
                    at.as_f64(),
                    Some(7.0),
                    "the event time is not the ledger's stamp"
                );
                (id.clone(), *from, *to)
            }
            other => panic!("unexpected event {other:?}"),
        })
        .collect()
}

fn ready(durable: &mut Durable<Stamping>, id: &str, priority: Priority) {
    let submit = Command::Submit {
        id: id.to_owned(),
        priority,
        playback: Playback::Play,
    };
    durable.apply(submit).unwrap();
    assert_eq!(durable.next_synthesis().unwrap().as_deref(), Some(id));
    durable.apply(Command::AudioReady(id.to_owned())).unwrap();
}

#[test]
fn a_preemption_suspends_the_speaker_before_starting_the_alert() {
    let mut durable = Durable::recover(Stamping::default()).unwrap();
    durable.apply(Command::Resume).unwrap();
    ready(&mut durable, "base", Priority::Normal);
    durable.plan_playback().unwrap();
    ready(&mut durable, "alert", Priority::Preempt);
    let _earlier = durable.take_events();
    durable.plan_playback().unwrap();
    assert_eq!(
        transitions(&durable.take_events()),
        [
            changed("base", State::Playing, State::Paused),
            changed("alert", State::Ready, State::Playing)
        ]
    );
}

#[test]
fn a_clear_skips_preempted_speakers_before_cancelling_pending_work_in_queue_order() {
    let mut durable = Durable::recover(Stamping::default()).unwrap();
    durable.apply(Command::Resume).unwrap();
    ready(&mut durable, "base", Priority::Normal);
    durable.plan_playback().unwrap();
    for id in ["later", "last"] {
        durable
            .apply(Command::Submit {
                id: id.to_owned(),
                priority: Priority::Normal,
                playback: Playback::Play,
            })
            .unwrap();
    }
    ready(&mut durable, "alert", Priority::Preempt);
    durable.plan_playback().unwrap();
    let _earlier = durable.take_events();
    durable.apply(Command::ClearQueue).unwrap();
    assert_eq!(
        transitions(&durable.take_events()),
        [
            changed("base", State::Paused, State::Skipped),
            changed("later", State::Queued, State::Cancelled),
            changed("last", State::Queued, State::Cancelled),
        ]
    );
}

#[test]
fn a_change_the_ledger_did_not_record_produces_no_event() {
    let mut durable = Durable::recover(Stamping::default()).unwrap();
    durable
        .apply(Command::Submit {
            id: "a".to_owned(),
            priority: Priority::Normal,
            playback: Playback::Play,
        })
        .unwrap();
    let _earlier = durable.take_events();
    let mut refusing = Durable::recover(Stamping { refusing: true }).unwrap();
    refusing
        .apply(Command::Submit {
            id: "a".to_owned(),
            priority: Priority::Normal,
            playback: Playback::Play,
        })
        .unwrap();
    assert!(refusing.next_synthesis().is_err());
    assert!(
        refusing.take_events().is_empty(),
        "an unrecorded change was announced"
    );
}

#[test]
fn a_reorder_announces_the_new_plan() {
    let mut durable = Durable::recover(Stamping::default()).unwrap();
    for id in ["a", "b"] {
        durable
            .apply(Command::Submit {
                id: id.to_owned(),
                priority: Priority::Normal,
                playback: Playback::Play,
            })
            .unwrap();
    }
    let _earlier = durable.take_events();
    durable
        .apply(Command::Reorder(vec!["b".to_owned(), "a".to_owned()]))
        .unwrap();
    assert_eq!(
        durable.take_events(),
        [Event::PlanReordered {
            ids: vec!["b".to_owned(), "a".to_owned()]
        }]
    );
}
