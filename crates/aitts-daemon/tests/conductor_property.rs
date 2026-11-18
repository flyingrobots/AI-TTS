// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (pure state, generated operation sequences).
//! Property: random queue operations give the same pending plan as a list model.
//! Oracle: a plain list written from the Python rules, not from the conductor: normal
//! work joins the back, urgent work the front, cancel and failure remove, clear
//! empties, and reorder replaces the list. Replay with `PROPTEST_RNG_SEED=<seed>
//! cargo test -p aitts-daemon --test conductor_property`; the default seed is 130.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use aitts_daemon::conductor::{Command, Conductor};
use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;
use proptest::prelude::*;
use proptest::strategy::ValueTree;
use proptest::test_runner::{Config, RngSeed, TestRunner};

#[derive(Clone, Copy, Debug)]
enum Step {
    Submit(Priority),
    Cancel(usize),
    Synthesize,
    Ready(usize),
    Fail(usize),
    Clear,
    Reorder(u64),
}

fn step() -> impl Strategy<Value = Step> {
    let priority = prop_oneof![Just(Priority::Normal), Just(Priority::Urgent)];
    prop_oneof![
        4 => priority.prop_map(Step::Submit),
        2 => any::<usize>().prop_map(Step::Cancel),
        2 => Just(Step::Synthesize),
        2 => any::<usize>().prop_map(Step::Ready),
        1 => any::<usize>().prop_map(Step::Fail),
        1 => Just(Step::Clear),
        2 => any::<u64>().prop_map(Step::Reorder),
    ]
}

fn config() -> Config {
    let mut config = Config {
        cases: 256,
        max_shrink_iters: 2_048,
        ..Config::default()
    };
    if matches!(config.rng_seed, RngSeed::Random) {
        config.rng_seed = RngSeed::Fixed(130);
    }
    config
}

fn pick(ids: &[String], index: usize) -> Option<&String> {
    ids.get(index.checked_rem(ids.len())?)
}

fn synthesizing(conductor: &Conductor) -> Vec<String> {
    let clips = conductor.clips().into_iter();
    clips
        .filter(|clip| clip.state == State::Synthesizing)
        .map(|clip| clip.id)
        .collect()
}

fn pending(conductor: &Conductor) -> Vec<String> {
    let owed = [State::Queued, State::Synthesizing, State::Ready];
    let clips = conductor.clips().into_iter();
    clips
        .filter(|clip| owed.contains(&clip.state))
        .map(|clip| clip.id)
        .collect()
}

/// Rotate by a seed-chosen amount and reverse on odd seeds: a permutation that the
/// generator controls without a second random source.
fn permute(model: &[String], seed: u64) -> Vec<String> {
    let mut permuted = model.to_vec();
    if let Some(shift) = usize::try_from(seed)
        .ok()
        .and_then(|seed| seed.checked_rem(model.len()))
    {
        permuted.rotate_left(shift);
    }
    if seed % 2 == 1 {
        permuted.reverse();
    }
    permuted
}

/// The class of an effective step, or `None` when the step changes nothing.
fn class(conductor: &Conductor, model: &[String], step: Step) -> Option<usize> {
    let busy = !synthesizing(conductor).is_empty();
    match step {
        Step::Submit(Priority::Urgent) => Some(0),
        Step::Cancel(_) if !model.is_empty() => Some(1),
        Step::Ready(_) if busy => Some(2),
        Step::Fail(_) if busy => Some(3),
        Step::Clear if !model.is_empty() => Some(4),
        Step::Reorder(_) if model.len() >= 2 => Some(5),
        _ => None,
    }
}

fn run(conductor: &mut Conductor, model: &mut Vec<String>, next: &mut u32, step: Step) {
    match step {
        Step::Submit(priority) => {
            *next += 1;
            let id = format!("utt_{next}");
            let command = Command::Submit {
                id: id.clone(),
                priority,
                playback: Playback::Play,
            };
            conductor.apply(command).unwrap();
            if priority == Priority::Normal {
                model.push(id);
            } else {
                model.insert(0, id);
            }
        }
        Step::Cancel(index) => {
            if let Some(id) = pick(model, index).cloned() {
                conductor.apply(Command::Cancel(id.clone())).unwrap();
                model.retain(|kept| *kept != id);
            }
        }
        Step::Synthesize => {
            conductor.next_synthesis();
        }
        Step::Ready(index) => {
            if let Some(id) = pick(&synthesizing(conductor), index) {
                conductor.apply(Command::AudioReady(id.clone())).unwrap();
            }
        }
        Step::Fail(index) => {
            if let Some(id) = pick(&synthesizing(conductor), index).cloned() {
                conductor
                    .apply(Command::SynthesisFailed(id.clone()))
                    .unwrap();
                model.retain(|kept| *kept != id);
            }
        }
        Step::Clear => {
            conductor.apply(Command::ClearQueue).unwrap();
            model.clear();
        }
        Step::Reorder(seed) => {
            *model = permute(model, seed);
            conductor.apply(Command::Reorder(model.clone())).unwrap();
        }
    }
}

proptest! {
    #![proptest_config(config())]

    #[test]
    fn random_operations_give_the_model_plan(steps in prop::collection::vec(step(), 0..40)) {
        let mut conductor = Conductor::new();
        let mut model = Vec::new();
        let mut next = 0;
        for step in steps {
            run(&mut conductor, &mut model, &mut next, step);
            prop_assert_eq!(pending(&conductor), model.clone(), "after {:?}", step);
        }
    }
}

/// Rule 5 corpus classification: each effective operation class must occur in at
/// least a tenth of the generated cases, so the property cannot pass on a corpus
/// of no-ops. Oracle: the class definitions above.
#[test]
fn the_generated_corpus_exercises_every_operation_class() {
    const NAMES: [&str; 6] = [
        "urgent submit",
        "cancel",
        "ready",
        "fail",
        "clear",
        "reorder",
    ];
    let config = config();
    let seed = format!("{:?}", config.rng_seed);
    let mut runner = TestRunner::new(config.clone());
    let strategy = prop::collection::vec(step(), 0..40);
    let mut cases_with = [0_u32; 6];
    for _ in 0..config.cases {
        let steps = strategy.new_tree(&mut runner).unwrap().current();
        let (mut conductor, mut model, mut next) = (Conductor::new(), Vec::new(), 0);
        let mut hit_classes = [false; 6];
        for step in steps {
            if let Some(index) = class(&conductor, &model, step) {
                hit_classes[index] = true;
            }
            run(&mut conductor, &mut model, &mut next, step);
        }
        for (count, hit) in cases_with.iter_mut().zip(hit_classes) {
            *count += u32::from(hit);
        }
    }
    println!(
        "seed {seed}: cases per class {:?}",
        NAMES.iter().zip(cases_with).collect::<Vec<_>>()
    );
    for (name, count) in NAMES.iter().zip(cases_with) {
        assert!(
            count * 10 >= config.cases,
            "class {name} in {count} of {} cases, seed {seed}",
            config.cases
        );
    }
}
