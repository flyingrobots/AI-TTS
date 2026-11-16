// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: Python model.py transition table and architecture section 9.

use aitts_domain::sensitivity::{EngineLocality, RemoteTextRefused, Sensitivity, admit};
use aitts_domain::utterance::{InvalidTransition, State};
use proptest::prelude::*;
mod support;

const STATES: [State; 10] = [
    State::Submitted,
    State::Queued,
    State::Synthesizing,
    State::Ready,
    State::Playing,
    State::Paused,
    State::Played,
    State::Skipped,
    State::Cancelled,
    State::Failed,
];

// Independently copied transition ledger. It does not call the implementation.
const LEGAL: [(State, State); 18] = [
    (State::Submitted, State::Queued),
    (State::Queued, State::Synthesizing),
    (State::Queued, State::Cancelled),
    (State::Synthesizing, State::Ready),
    (State::Synthesizing, State::Failed),
    (State::Synthesizing, State::Cancelled),
    (State::Synthesizing, State::Queued),
    (State::Ready, State::Playing),
    (State::Ready, State::Cancelled),
    (State::Ready, State::Failed),
    (State::Playing, State::Played),
    (State::Playing, State::Paused),
    (State::Playing, State::Skipped),
    (State::Playing, State::Failed),
    (State::Paused, State::Playing),
    (State::Paused, State::Played),
    (State::Paused, State::Skipped),
    (State::Paused, State::Failed),
];

#[test]
fn every_state_pair_matches_the_python_transition_ledger() {
    for source in STATES {
        for destination in STATES {
            let expected = if LEGAL.contains(&(source, destination)) {
                Ok(destination)
            } else {
                Err(InvalidTransition {
                    source,
                    destination,
                })
            };
            assert_eq!(
                source.transition(destination),
                expected,
                "{source:?} -> {destination:?}"
            );
        }
    }
}

#[test]
fn terminal_states_match_the_python_terminal_set() {
    let expected = [
        State::Played,
        State::Skipped,
        State::Cancelled,
        State::Failed,
    ];
    let actual: Vec<_> = STATES
        .into_iter()
        .filter(|state| state.is_terminal())
        .collect();
    assert_eq!(actual, expected);
}

#[test]
fn all_sensitivity_and_locality_pairs_follow_disclosure_policy() {
    for sensitivity in [
        Sensitivity::Public,
        Sensitivity::Internal,
        Sensitivity::Confidential,
    ] {
        assert_eq!(admit(sensitivity, EngineLocality::Local), Ok(()));
        let expected = if sensitivity == Sensitivity::Public {
            Ok(())
        } else {
            Err(RemoteTextRefused { sensitivity })
        };
        assert_eq!(admit(sensitivity, EngineLocality::Remote), expected);
    }
}

proptest! {
    #![proptest_config(support::config())]
    #[test]
    fn arbitrary_sequences_never_enter_an_illegal_state(destinations in prop::collection::vec(prop::sample::select(STATES.to_vec()), 0..64)) {
        let mut state = State::Submitted;
        for destination in destinations {
            let previous = state;
            match state.transition(destination) {
                Ok(accepted) => {
                    prop_assert!(LEGAL.contains(&(previous, accepted)));
                    prop_assert_eq!(accepted, destination);
                    state = accepted;
                }
                Err(error) => {
                    prop_assert!(!LEGAL.contains(&(previous, destination)));
                    prop_assert_eq!(error, InvalidTransition { source: previous, destination });
                }
            }
            if previous.is_terminal() { prop_assert_eq!(state, previous); }
        }
    }
}
