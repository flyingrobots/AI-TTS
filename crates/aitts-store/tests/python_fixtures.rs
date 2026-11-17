// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files). Oracle: the JSON the Python `Store` read back
//! from each fixture database, written by `tests/fixtures/generate.py`.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use aitts_store::Store;
use support::{FixedClock, RECOVER_AT, copy_fixture, dump, expected, expected_ids};

fn read(name: &str, recover: bool) {
    let (_dir, path) = copy_fixture(name);
    let store = Store::open(&path, FixedClock(RECOVER_AT)).unwrap();
    if recover {
        store.queue().recover().unwrap();
    }
    let want = expected(name);
    assert_eq!(dump(&store, &expected_ids(&want)), want, "{name}");
}

#[test]
fn golden_database_reads_every_row_as_python_does() {
    read("golden", false);
}

#[test]
fn old_database_without_engine_column_migrates_as_python_does() {
    read("legacy", true);
}

#[test]
fn restart_recovery_matches_python_after_each_crash_point() {
    for crash_after in 0..4 {
        read(&format!("crash-{crash_after}"), true);
    }
}

#[test]
fn restart_recovery_matches_python_in_the_middle_of_streaming_jobs() {
    read("streaming", true);
}
