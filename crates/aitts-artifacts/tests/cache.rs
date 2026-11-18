// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files). Contract: `GeneratedStorage::inventory`
//! rows and what `remove` deletes. Oracle: `fixtures/cache`, where the Python
//! `GeneratedStorage` read and then pruned the same cache directory with the same
//! modification times (`scripts/generate_cache_fixtures.py`). Rows are compared
//! as parsed JSON.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::collections::BTreeSet;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::time::{Duration, UNIX_EPOCH};

use aitts_artifacts::cache::GeneratedStorage;
use serde_json::{Value, json};

const FIXTURE: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/cache");

fn fixture_json(name: &str) -> Value {
    serde_json::from_slice(&fs::read(Path::new(FIXTURE).join(name)).unwrap()).unwrap()
}

fn copy_tree(from: &Path, to: &Path) {
    fs::create_dir_all(to).unwrap();
    for entry in fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).unwrap();
        }
    }
}

/// A private copy of the fixture cache with the Python script's times and link.
fn python_cache() -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    copy_tree(&Path::new(FIXTURE).join("root"), &root);
    for (name, mtime) in fixture_json("mtimes.json").as_object().unwrap() {
        let time = UNIX_EPOCH + Duration::from_secs_f64(mtime.as_f64().unwrap());
        fs::File::options()
            .write(true)
            .open(root.join(name))
            .unwrap()
            .set_modified(time)
            .unwrap();
    }
    symlink("clip-a", root.join("linked")).unwrap();
    (dir, root)
}

fn set(items: &[&str]) -> BTreeSet<String> {
    items.iter().map(|item| (*item).to_owned()).collect()
}

#[test]
fn the_inventory_of_a_python_cache_equals_the_python_inventory() {
    let (_dir, root) = python_cache();
    let rows = GeneratedStorage::new(&root)
        .inventory(&set(&["held"]))
        .unwrap();
    let ours: Vec<Value> = rows
        .iter()
        .map(|row| {
            json!({
                "id": row.id,
                "bytes": row.bytes,
                "modified_at": row.modified_at,
                "protected": row.protected,
                "preview": row.preview,
            })
        })
        .collect();
    assert_eq!(Value::from(ours), fixture_json("inventory.json"));
}

#[test]
fn a_missing_cache_root_is_an_empty_inventory() {
    let dir = tempfile::tempdir().unwrap();
    let rows = GeneratedStorage::new(dir.path().join("absent"))
        .inventory(&BTreeSet::new())
        .unwrap();
    assert_eq!(rows, []);
}

#[test]
fn removal_counts_equal_the_python_counts() {
    let (_dir, root) = python_cache();
    let ids = set(&["clip-a", "held", "streaming", "legacy", "absent"]);
    let removal = GeneratedStorage::new(&root)
        .remove(&ids, &set(&["held"]))
        .unwrap();
    let python = &fixture_json("removal.json")["result"];
    assert_eq!(
        json!({"removed": removal.removed, "protected": removal.protected, "failed": removal.failed}),
        *python
    );
}

#[test]
fn removal_leaves_the_python_cache_members() {
    let (_dir, root) = python_cache();
    let ids = set(&["clip-a", "held", "streaming", "legacy", "absent"]);
    GeneratedStorage::new(&root)
        .remove(&ids, &set(&["held"]))
        .unwrap();
    let mut left: Vec<String> = fs::read_dir(&root)
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    left.sort();
    assert_eq!(json!(left), fixture_json("removal.json")["left"]);
}

#[test]
fn removal_never_follows_a_symbolic_link_out_of_the_cache() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    let outside = dir.path().join("outside");
    fs::create_dir_all(&root).unwrap();
    fs::create_dir(&outside).unwrap();
    fs::write(outside.join("keep.wav"), b"RIFF").unwrap();
    symlink(&outside, root.join("victim")).unwrap();
    symlink(outside.join("keep.wav"), root.join("victim.wav")).unwrap();
    GeneratedStorage::new(&root)
        .remove(&set(&["victim"]), &BTreeSet::new())
        .unwrap();
    assert!(outside.join("keep.wav").exists());
}
