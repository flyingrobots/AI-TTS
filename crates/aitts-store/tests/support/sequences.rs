// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
#![allow(
    clippy::indexing_slicing,
    clippy::too_many_lines,
    clippy::panic,
    reason = "a test driver over fixed tables; one match keeps both stores' steps aligned"
)]

//! Random store operation sequences, replayed identically by Rust and by
//! `scripts/generate_store_fixtures.py` against the Python store.
//!
//! The driver sets the clock to `1000 + step` before each step, so both stores see
//! the same time however often they read it.

use std::cell::Cell;
use std::rc::Rc;

use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{Clock, Priority, Sensitivity, State, Store, names};
use proptest::prelude::*;
use proptest::strategy::ValueTree;
use proptest::test_runner::{Config, RngSeed, TestRunner};
use serde_json::{Value, json};

/// The fixed seed and size of the checked-in corpus; CI stays bounded.
pub(crate) const SEED: u64 = 135;
pub(crate) const CASES: usize = 128;
const MAX_OPS: usize = 40;

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
const PRIORITIES: [Priority; 3] = [Priority::Normal, Priority::Urgent, Priority::Preempt];
const SENSITIVITIES: [Sensitivity; 3] = [
    Sensitivity::Public,
    Sensitivity::Internal,
    Sensitivity::Confidential,
];
const SOURCES: [&str; 3] = ["agent-a", "agent-b", "agent-c"];
const VOICES: [&str; 3] = ["af_heart", "bm_daniel", "ff_siwis"];
const KEYS: [&str; 2] = ["speed", "default_voice"];

/// One store operation. Indexes select from the fixed tables above; `utt` selects
/// a submitted utterance by submission order and may name one that does not exist.
#[derive(Clone, Debug)]
pub(crate) enum Op {
    Submit {
        priority: usize,
        sensitivity: usize,
        at_head: bool,
        segmented: bool,
        playback: bool,
    },
    Transition {
        utt: usize,
        state: usize,
        audio: bool,
    },
    /// Move to the `choice`-th legal successor, in `STATES` order, of the current state.
    Advance {
        utt: usize,
        choice: usize,
        audio: bool,
    },
    AdvanceSegment {
        utt: usize,
        index: i64,
        choice: usize,
    },
    TransitionSegment {
        utt: usize,
        index: i64,
        state: usize,
    },
    Set {
        key: usize,
        value: usize,
    },
    Claim {
        source: usize,
        voice: usize,
    },
    Pin {
        source: usize,
        voice: usize,
    },
    Release {
        source: usize,
    },
    RemoveHistory {
        utt: usize,
    },
    ClearHistory,
    Recover,
}

fn op() -> impl Strategy<Value = Op> {
    prop_oneof![
        3 => (0..3_usize, 0..3_usize, any::<bool>(), any::<bool>(), any::<bool>()).prop_map(
            |(priority, sensitivity, at_head, segmented, playback)| Op::Submit {
                priority, sensitivity, at_head, segmented, playback,
            }
        ),
        2 => (0..6_usize, 0..10_usize, any::<bool>())
            .prop_map(|(utt, state, audio)| Op::Transition { utt, state, audio }),
        8 => (0..3_usize, 0..4_usize, any::<bool>())
            .prop_map(|(utt, choice, audio)| Op::Advance { utt, choice, audio }),
        4 => (0..3_usize, 0..2_i64, 0..4_usize)
            .prop_map(|(utt, index, choice)| Op::AdvanceSegment { utt, index, choice }),
        1 => (0..6_usize, 0..3_i64, 0..10_usize)
            .prop_map(|(utt, index, state)| Op::TransitionSegment { utt, index, state }),
        1 => (0..2_usize, 0..3_usize).prop_map(|(key, value)| Op::Set { key, value }),
        1 => (0..3_usize, 0..3_usize).prop_map(|(source, voice)| Op::Claim { source, voice }),
        1 => (0..3_usize, 0..3_usize).prop_map(|(source, voice)| Op::Pin { source, voice }),
        1 => (0..3_usize).prop_map(|source| Op::Release { source }),
        1 => (0..6_usize).prop_map(|utt| Op::RemoveHistory { utt }),
        1 => Just(Op::ClearHistory),
        1 => Just(Op::Recover),
    ]
}

/// The corpus sequences, reproducible from [`SEED`].
pub(crate) fn generate() -> Vec<Vec<Op>> {
    let config = Config {
        rng_seed: RngSeed::Fixed(SEED),
        ..Config::default()
    };
    let mut runner = TestRunner::new(config);
    let strategy = proptest::collection::vec(op(), 1..=MAX_OPS);
    (0..CASES)
        .map(|_| {
            strategy
                .new_tree(&mut runner)
                .map_or_else(|_| Vec::new(), |tree| tree.current())
        })
        .collect()
}

fn pick<T: Copy>(table: &[T], index: usize) -> T {
    table[index % table.len()]
}

/// The JSON form `generate_store_fixtures.py` replays.
pub(crate) fn to_json(op: &Op) -> Value {
    match *op {
        Op::Submit {
            priority,
            sensitivity,
            at_head,
            segmented,
            playback,
        } => json!({
            "op": "submit",
            "priority": names::priority(pick(&PRIORITIES, priority)),
            "sensitivity": names::sensitivity(pick(&SENSITIVITIES, sensitivity)),
            "at_head": at_head, "segmented": segmented, "playback": playback,
        }),
        Op::Transition { utt, state, audio } => json!({
            "op": "transition", "utt": utt,
            "state": names::state(pick(&STATES, state)), "audio": audio,
        }),
        Op::Advance { utt, choice, audio } => json!({
            "op": "advance", "utt": utt, "choice": choice, "audio": audio,
        }),
        Op::AdvanceSegment { utt, index, choice } => json!({
            "op": "advance_segment", "utt": utt, "index": index, "choice": choice,
        }),
        Op::TransitionSegment { utt, index, state } => json!({
            "op": "transition_segment", "utt": utt, "index": index,
            "state": names::state(pick(&STATES, state)),
        }),
        Op::Set { key, value } => {
            json!({"op": "set", "key": pick(&KEYS, key), "value": value.to_string()})
        }
        Op::Claim { source, voice } => {
            json!({"op": "claim", "source": pick(&SOURCES, source), "voice": pick(&VOICES, voice)})
        }
        Op::Pin { source, voice } => {
            json!({"op": "pin", "source": pick(&SOURCES, source), "voice": pick(&VOICES, voice)})
        }
        Op::Release { source } => json!({"op": "release", "source": pick(&SOURCES, source)}),
        Op::RemoveHistory { utt } => json!({"op": "remove_history", "utt": utt}),
        Op::ClearHistory => json!({"op": "clear_history"}),
        Op::Recover => json!({"op": "recover"}),
    }
}

/// The `choice`-th legal successor of `state`, wrapping, or `None` when terminal.
fn successor(state: State, choice: usize) -> Option<State> {
    let legal: Vec<State> = STATES
        .iter()
        .copied()
        .filter(|to| state.transition(*to).is_ok())
        .collect();
    let count = legal.len();
    legal.get(choice.checked_rem(count)?).copied()
}

struct DriverClock(Rc<Cell<f64>>);

impl Clock for DriverClock {
    fn now(&self) -> f64 {
        self.0.get()
    }
}

fn utt_id(utt: usize) -> String {
    format!("utt_{:04}", utt + 1)
}

fn outcome<T: ToString>(result: aitts_store::Result<T>) -> String {
    result.map_or_else(|_| "error".to_owned(), |value| value.to_string())
}

/// Replay `ops` on a new database at `path`; return each step's outcome.
pub(crate) fn replay(path: &std::path::Path, ops: &[Op]) -> (Store, Vec<String>, Vec<String>) {
    let now = Rc::new(Cell::new(1_000.0));
    let store = Store::open(path, DriverClock(Rc::clone(&now))).unwrap_or_else(|e| panic!("{e}"));
    let mut submitted = 0_usize;
    let mut outcomes = Vec::new();
    for (step, op) in (0_u32..).zip(ops) {
        now.set(1_000.0 + f64::from(step));
        let queue = store.queue();
        let result = match *op {
            Op::Submit {
                priority,
                sensitivity,
                at_head,
                segmented,
                playback,
            } => {
                let mut new = NewUtterance::new(
                    utt_id(submitted),
                    format!("text {submitted}"),
                    "af_heart".to_owned(),
                    1.0,
                );
                new.priority = pick(&PRIORITIES, priority);
                new.sensitivity = pick(&SENSITIVITIES, sensitivity);
                new.at_head = at_head;
                new.playback = playback;
                new.segments = segmented.then(|| vec!["one".to_owned(), "two".to_owned()]);
                submitted += 1;
                outcome(queue.submit(&new).map(|_| "ok"))
            }
            Op::Transition { utt, state, audio } => {
                let fields = Fields {
                    audio_path: audio.then(|| format!("/cache/{step}.wav")),
                    duration_ms: audio.then_some(100),
                    ..Fields::default()
                };
                outcome(
                    queue
                        .transition(&utt_id(utt), pick(&STATES, state), &fields)
                        .map(|_| "ok"),
                )
            }
            Op::Advance { utt, choice, audio } => {
                let fields = Fields {
                    audio_path: audio.then(|| format!("/cache/{step}.wav")),
                    duration_ms: audio.then_some(100),
                    ..Fields::default()
                };
                let id = utt_id(utt);
                match queue.get(&id) {
                    Ok(Some(found)) => match successor(found.state, choice) {
                        Some(to) => outcome(queue.transition(&id, to, &fields).map(|_| "ok")),
                        None => "terminal".to_owned(),
                    },
                    _ => "error".to_owned(),
                }
            }
            Op::AdvanceSegment { utt, index, choice } => {
                let id = utt_id(utt);
                let current = queue
                    .segments(&id)
                    .ok()
                    .and_then(|all| all.into_iter().find(|segment| segment.index == index));
                match current {
                    Some(found) => match successor(found.state, choice) {
                        Some(to) => outcome(
                            queue
                                .transition_segment(&id, index, to, &Fields::default())
                                .map(|_| "ok"),
                        ),
                        None => "terminal".to_owned(),
                    },
                    None => "error".to_owned(),
                }
            }
            Op::TransitionSegment { utt, index, state } => outcome(
                queue
                    .transition_segment(
                        &utt_id(utt),
                        index,
                        pick(&STATES, state),
                        &Fields::default(),
                    )
                    .map(|_| "ok"),
            ),
            Op::Set { key, value } => outcome(
                store
                    .settings()
                    .set(pick(&KEYS, key), &value.to_string())
                    .map(|()| "ok"),
            ),
            Op::Claim { source, voice } => outcome(
                store
                    .voices()
                    .claim(pick(&SOURCES, source), pick(&VOICES, voice))
                    .map(|_| "ok"),
            ),
            Op::Pin { source, voice } => outcome(
                store
                    .voices()
                    .pin(pick(&SOURCES, source), pick(&VOICES, voice))
                    .map(|_| "ok"),
            ),
            Op::Release { source } => outcome(store.voices().release(pick(&SOURCES, source))),
            Op::RemoveHistory { utt } => outcome(store.history().remove(&utt_id(utt))),
            Op::ClearHistory => outcome(store.history().clear()),
            Op::Recover => outcome(queue.recover().map(|()| "ok")),
        };
        outcomes.push(result);
    }
    let ids = (0..submitted)
        .map(utt_id)
        .filter(|id| matches!(store.queue().get(id), Ok(Some(_))))
        .collect();
    (store, ids, outcomes)
}
