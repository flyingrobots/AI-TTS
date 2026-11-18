// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files). Property: for any sequence of appends,
//! fills, reads and seeks, every read returns exactly the bytes written at its
//! position, and the ring never holds more than its capacity. Oracle: a model
//! that keeps every written byte in a `Vec`. The interleaving of production and
//! reading is the generated sequence itself, so it is replayable from the seed.
//!
//! Replay: `PROPTEST_RNG_SEED=<seed> cargo test -p aitts-artifacts --test spool_property`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::print_stderr,
    clippy::indexing_slicing,
    clippy::as_conversions,
    reason = "test code fails loudly"
)]

use aitts_artifacts::spool::Spool;
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};

#[derive(Debug, Clone)]
enum Op {
    Append(Vec<u8>),
    Fill,
    Read(usize),
    Seek(u64),
}

fn op() -> impl Strategy<Value = Op> {
    prop_oneof![
        3 => prop::collection::vec(any::<[u8; 2]>(), 0..12)
            .prop_map(|frames| Op::Append(frames.concat())),
        2 => Just(Op::Fill),
        3 => (0usize..10).prop_map(Op::Read),
        1 => (0u64..64).prop_map(Op::Seek),
    ]
}

fn seed() -> u64 {
    std::env::var("PROPTEST_RNG_SEED")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or_else(|| {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap();
            now.as_secs() ^ u64::from(now.subsec_nanos())
        })
}

fn check(ops: &[Op], capacity: usize) -> Result<(), TestCaseError> {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&dir.path().join(".s.wav.part"), capacity).unwrap();
    let mut written: Vec<u8> = Vec::new();
    let mut position = 0usize;
    for op in ops {
        match op {
            Op::Append(pcm) => {
                spool.append(pcm).unwrap();
                written.extend(pcm);
            }
            Op::Fill => {
                spool.fill();
            }
            Op::Read(frames) => {
                let read = spool.read(*frames);
                let start = (position * 2).min(written.len());
                let end = (start + read.pcm.len()).min(written.len());
                prop_assert_eq!(
                    &read.pcm[..],
                    &written[start..end],
                    "bytes at frame {}",
                    position
                );
                position += read.pcm.len() / 2;
                prop_assert_eq!(read.position_frames, position as u64);
            }
            Op::Seek(target) => {
                spool.seek(*target);
                position = usize::try_from(*target).unwrap();
            }
        }
        prop_assert!(spool.buffered_frames() <= capacity, "ring over capacity");
    }
    Ok(())
}

#[test]
fn reads_return_the_written_bytes_for_random_write_and_seek_sequences() {
    let seed = seed();
    eprintln!("spool property seed {seed}; replay with PROPTEST_RNG_SEED={seed}");
    let mut seed_bytes = [0u8; 32];
    seed_bytes[..8].copy_from_slice(&seed.to_le_bytes());
    let rng = TestRng::from_seed(RngAlgorithm::ChaCha, &seed_bytes);
    let mut runner = TestRunner::new_with_rng(
        Config {
            cases: 256,
            failure_persistence: None,
            ..Config::default()
        },
        rng,
    );
    let strategy = (prop::collection::vec(op(), 0..40), 1usize..8);
    let nonempty_reads = std::cell::Cell::new(0usize);
    runner
        .run(&strategy, |(ops, capacity)| {
            nonempty_reads.set(
                nonempty_reads.get()
                    + usize::from(ops.iter().any(|op| matches!(op, Op::Read(n) if *n > 0))),
            );
            check(&ops, capacity)
        })
        .unwrap();
    // Corpus classification: most cases must read something.
    let nonempty_reads = nonempty_reads.get();
    eprintln!("{nonempty_reads} of 256 cases read frames");
    assert!(
        nonempty_reads > 128,
        "only {nonempty_reads} of 256 cases read any frames"
    );
}

#[test]
fn named_case_a_seek_past_the_written_end_waits_for_production() {
    let ops = [
        Op::Append(vec![1, 0]),
        Op::Seek(3),
        Op::Fill,
        Op::Read(4),
        Op::Append(vec![2, 0, 3, 0, 4, 0, 5, 0]),
        Op::Fill,
        Op::Read(4),
    ];
    check(&ops, 4).unwrap();
}
