// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files). Oracle: `golden.json`, what Python read after the
//! Python daemon performed the same operations, and the Python-written schema.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use aitts_store::Store;
use rusqlite::Connection;
use support::{SteppingClock, copy_fixture, dump, expected, expected_ids, fixture, golden_ops};

#[test]
fn rust_writes_the_rows_python_wrote_for_the_same_operations() {
    let dir = tempfile::tempdir().unwrap();
    let store = Store::open(
        &dir.path().join("state.db"),
        SteppingClock::starting_at(1_000.0),
    )
    .unwrap();
    golden_ops::write(&store).unwrap();
    let want = expected("golden");
    assert_eq!(dump(&store, &expected_ids(&want)), want);
}

#[test]
fn checked_in_rust_written_fixture_is_current() {
    let store = Store::open(
        &copy_fixture("rust-written").1,
        SteppingClock::starting_at(0.0),
    )
    .unwrap();
    let want = expected("golden");
    assert_eq!(dump(&store, &expected_ids(&want)), want);
}

fn schema(path: &std::path::Path) -> (i64, Vec<(String, String, Option<String>)>) {
    let db = Connection::open(path).unwrap();
    let version = db
        .query_row("PRAGMA user_version", [], |row| row.get(0))
        .unwrap();
    let mut statement = db
        .prepare("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
        .unwrap();
    let rows = statement
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    (version, rows)
}

#[test]
fn a_new_database_has_the_python_schema_and_version() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    Store::open(&path, SteppingClock::starting_at(0.0))
        .unwrap()
        .close()
        .unwrap();
    assert_eq!(schema(&path), schema(&fixture("golden.db")));
}

#[test]
fn opening_never_changes_the_schema_version() {
    for name in ["golden", "legacy", "streaming"] {
        let (_dir, path) = copy_fixture(name);
        let before = schema(&path).0;
        Store::open(&path, SteppingClock::starting_at(0.0))
            .unwrap()
            .close()
            .unwrap();
        assert_eq!(schema(&path).0, before, "{name}");
    }
}
