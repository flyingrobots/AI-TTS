// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small. Oracle: store.py order queries and playback.py preemption/restore rules.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_domain::plan::{
    Entry, Hold, InvalidOrderKey, OrderKey, Playback, Priority, ResumeFrame, SegmentIndex,
    UtteranceId, admission_key, ordered, preemption, resume,
};
use aitts_domain::utterance::State;
use proptest::prelude::*;
mod support;

fn entry(id: &str, key: f64, priority: Priority, state: State) -> Entry<'_> {
    Entry {
        id: UtteranceId(id),
        order: OrderKey::new(key).unwrap(),
        priority,
        state,
        playback: Playback::Play,
    }
}

#[test]
fn keys_order_stably_and_priority_only_changes_admission() {
    let entries = [
        entry("tail", 3.0, Priority::Preempt, State::Ready),
        entry("a", 1.0, Priority::Normal, State::Ready),
        entry("b", 1.0, Priority::Urgent, State::Queued),
        entry("past", -8.0, Priority::Normal, State::Played),
    ];
    assert_eq!(
        ordered(&entries)
            .iter()
            .map(|item| item.id.0)
            .collect::<Vec<_>>(),
        ["past", "a", "b", "tail"]
    );
    assert_eq!(
        admission_key(&entries, Priority::Normal).unwrap().value(),
        4.0
    );
    for priority in [Priority::Urgent, Priority::Preempt] {
        assert_eq!(admission_key(&entries, priority).unwrap().value(), 0.0);
    }
    assert_eq!(admission_key(&[], Priority::Normal).unwrap().value(), 1.0);
    assert_eq!(admission_key(&[], Priority::Preempt).unwrap().value(), 0.0);
    let historical = [entry("completed", 8.0, Priority::Normal, State::Played)];
    assert_eq!(
        admission_key(&historical, Priority::Normal)
            .unwrap()
            .value(),
        9.0
    );
    let zeros = [
        entry("positive", 0.0, Priority::Normal, State::Ready),
        entry("negative", -0.0, Priority::Preempt, State::Ready),
    ];
    assert_eq!(ordered(&zeros), zeros);
    for invalid in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(OrderKey::new(invalid), Err(InvalidOrderKey));
    }
    assert_eq!(
        admission_key(
            &[entry("huge", f64::MAX, Priority::Normal, State::Ready)],
            Priority::Normal
        ),
        Err(InvalidOrderKey)
    );
}

#[test]
fn interruption_requires_ready_preempt_priority_earlier_key_and_open_hold() {
    let current = entry("speaker", 2.0, Priority::Normal, State::Playing);
    let candidate = entry("interrupt", 1.0, Priority::Preempt, State::Ready);
    assert_eq!(
        preemption(&[candidate], Some(current), Hold::Open),
        Some(candidate)
    );
    assert_eq!(preemption(&[candidate], None, Hold::Open), Some(candidate));
    assert_eq!(preemption(&[candidate], Some(current), Hold::Held), None);
    for rejected in [
        Entry {
            order: current.order,
            ..candidate
        },
        Entry {
            priority: Priority::Urgent,
            ..candidate
        },
        Entry {
            state: State::Synthesizing,
            ..candidate
        },
        Entry {
            playback: Playback::SynthesizeOnly,
            ..candidate
        },
    ] {
        assert_eq!(
            preemption(&[rejected], Some(current), Hold::Open),
            None,
            "{rejected:?}"
        );
    }
    let later = Entry {
        order: OrderKey::new(3.0).unwrap(),
        ..candidate
    };
    assert_eq!(
        preemption(
            &[later],
            Some(Entry {
                state: State::Played,
                ..current
            }),
            Hold::Open
        ),
        Some(later)
    );
    let first = Entry {
        id: UtteranceId("first"),
        order: OrderKey::new(0.0).unwrap(),
        ..candidate
    };
    assert_eq!(
        preemption(&[candidate, first], Some(current), Hold::Open),
        Some(first)
    );
}

#[test]
fn nested_preemption_restores_lifo_and_skips_missing_or_finished_speakers() {
    let a = ResumeFrame {
        id: UtteranceId("a"),
        segment: Some(SegmentIndex(7)),
    };
    let b = ResumeFrame {
        id: UtteranceId("b"),
        segment: None,
    };
    let mut stack = vec![
        a,
        b,
        ResumeFrame {
            id: UtteranceId("gone"),
            segment: None,
        },
        ResumeFrame {
            id: UtteranceId("finished"),
            segment: None,
        },
    ];
    let entries = [
        entry("a", 2.0, Priority::Normal, State::Paused),
        entry("b", 1.0, Priority::Preempt, State::Paused),
        entry("finished", 0.0, Priority::Preempt, State::Played),
    ];
    assert_eq!(resume(&mut stack, &entries), Some(b));
    assert_eq!(resume(&mut stack, &entries), Some(a));
    assert_eq!(resume(&mut stack, &entries), None);
    assert_eq!(stack, Vec::<ResumeFrame<'_>>::new());
}

proptest! {
    #![proptest_config(support::config())]
    #[test]
    fn generated_queue_order_is_a_stable_permutation(keys in prop::collection::vec(-8_i16..=8, 0..64)) {
        let ids: Vec<_> = (0..keys.len()).map(|index| index.to_string()).collect();
        let entries: Vec<_> = ids.iter().zip(&keys).map(|(id, key)| entry(id, f64::from(*key), Priority::Normal, State::Ready)).collect();
        let sorted = ordered(&entries);
        prop_assert_eq!(sorted.len(), entries.len());
        for original in &entries { prop_assert_eq!(sorted.iter().filter(|item| item.id == original.id).count(), 1); }
        for adjacent in sorted.windows(2) {
            let left = adjacent.first().unwrap();
            let right = adjacent.last().unwrap();
            prop_assert!(left.order <= right.order);
            if left.order == right.order {
                prop_assert!(left.id.0.parse::<usize>().unwrap() < right.id.0.parse::<usize>().unwrap());
            }
        }
        prop_assert_eq!(ordered(&sorted), sorted);
    }
}
