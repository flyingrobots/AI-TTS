// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files). Contract: the `Spool` API after a
//! refused creation or a producer failure. Oracles: a refused `create` changes
//! nothing on disk; `SpoolingPCMStream` lets a reader drain every frame that was
//! written before the producer's error, then ends with that error.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use aitts_artifacts::spool::Spool;

#[test]
fn a_zero_capacity_create_leaves_no_file() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("clip.wav");
    assert!(
        Spool::create(&path, 0).is_err(),
        "zero capacity was accepted"
    );
    assert!(!path.exists(), "a refused create left {}", path.display());
}

#[test]
fn a_reader_drains_the_written_prefix_after_a_producer_failure() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&dir.path().join("clip.wav"), 1).unwrap();
    // Two whole frames; the one-frame ring holds only the first.
    spool.append(&[1, 0, 2, 0]).unwrap();
    spool.finish(Some("worker exited".to_owned()));
    let first = spool.read(1);
    spool.fill();
    let second = spool.read(1);
    assert_eq!(
        (first.pcm, second.pcm.clone()),
        (vec![1, 0], vec![2, 0]),
        "second frame not drained"
    );
    assert!(
        second.ended && second.error.is_some(),
        "drained spool did not end with its error: {second:?}"
    );
}
