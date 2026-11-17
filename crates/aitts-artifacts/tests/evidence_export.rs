// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files). Contract: the evidence ZIP's entries and
//! the files `export` leaves. Oracle: `fixtures/evidence/python-export.zip`, which
//! the Python `ClipEvidence.export` wrote for `fixtures/evidence/root` and
//! `request.json` (`scripts/generate_evidence_fixtures.py`, clock and runtime pinned).

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::fs;
use std::io::Read as _;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::{Path, PathBuf};

use aitts_artifacts::evidence::ClipEvidence;
use serde_json::{Value, json};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/evidence");
const EXPORTED_AT: f64 = 1_800_000_000.5;

fn runtime() -> Value {
    json!({"os": "fixture", "architecture": "fixture"})
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

/// A private copy of the fixture root and the request with absolute audio paths.
fn scene() -> (tempfile::TempDir, PathBuf, Value, Vec<Value>) {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    copy_tree(&Path::new(FIXTURES).join("root"), &root);
    let request: Value =
        serde_json::from_slice(&fs::read(Path::new(FIXTURES).join("request.json")).unwrap())
            .unwrap();
    let clips = request["clips"]
        .as_array()
        .unwrap()
        .iter()
        .map(|clip| {
            let mut clip = clip.clone();
            if let Some(relative) = clip["audio_path"].as_str() {
                clip["audio_path"] = json!(root.join(relative).to_str().unwrap());
            }
            clip
        })
        .collect();
    (dir, root, request["item"].clone(), clips)
}

fn entries(path: &Path) -> Vec<(String, Vec<u8>)> {
    let mut archive = zip::ZipArchive::new(fs::File::open(path).unwrap()).unwrap();
    (0..archive.len())
        .map(|index| {
            let mut file = archive.by_index(index).unwrap();
            let mut bytes = Vec::new();
            file.read_to_end(&mut bytes).unwrap();
            (file.name().to_owned(), bytes)
        })
        .collect()
}

fn python_entries() -> Vec<(String, Vec<u8>)> {
    entries(&Path::new(FIXTURES).join("python-export.zip"))
}

#[test]
fn the_export_has_the_python_entry_names_in_the_python_order() {
    let (dir, root, item, clips) = scene();
    let out = dir.path().join("export.zip");
    ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    let names =
        |list: Vec<(String, Vec<u8>)>| list.into_iter().map(|(name, _)| name).collect::<Vec<_>>();
    assert_eq!(names(entries(&out)), names(python_entries()));
}

#[test]
fn every_entry_except_the_manifest_has_the_python_bytes() {
    let (dir, root, item, clips) = scene();
    let out = dir.path().join("export.zip");
    ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    let rust = entries(&out);
    let mut compared = 0;
    for (name, bytes) in python_entries()
        .into_iter()
        .filter(|(name, _)| name != "manifest.json")
    {
        let found = rust
            .iter()
            .find(|(other, _)| *other == name)
            .map(|(_, b)| b);
        assert_eq!(found, Some(&bytes), "entry {name}");
        compared += 1;
    }
    assert_eq!(compared, 14, "entries compared");
}

#[test]
fn the_manifest_has_the_python_fields_and_values() {
    let (dir, root, item, clips) = scene();
    let out = dir.path().join("export.zip");
    ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    let manifest = |list: Vec<(String, Vec<u8>)>| -> Value {
        let (_, bytes) = list
            .into_iter()
            .find(|(name, _)| name == "manifest.json")
            .unwrap();
        serde_json::from_slice(&bytes).unwrap()
    };
    assert_eq!(manifest(entries(&out)), manifest(python_entries()));
}

#[test]
fn the_report_lists_the_python_warnings() {
    let (dir, root, item, clips) = scene();
    let out = dir.path().join("export.zip");
    let report = ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    let (_, bytes) = python_entries()
        .into_iter()
        .find(|(n, _)| n == "manifest.json")
        .unwrap();
    let python: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(json!(report.warnings), python["warnings"]);
    assert_eq!(report.path, out);
}

#[test]
fn the_archive_is_owner_only() {
    let (dir, root, item, clips) = scene();
    let out = dir.path().join("export.zip");
    ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    assert_eq!(
        fs::metadata(&out).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[test]
fn an_existing_destination_is_refused_and_kept() {
    let (dir, root, item, clips) = scene();
    let out = dir.path().join("export.zip");
    fs::write(&out, b"mine").unwrap();
    assert!(
        ClipEvidence::new(&root)
            .export(&out, &item, &clips, EXPORTED_AT, &runtime())
            .is_err()
    );
    assert_eq!(fs::read(&out).unwrap(), b"mine");
}

#[test]
fn a_relative_or_non_zip_destination_is_refused() {
    let (dir, root, item, clips) = scene();
    let evidence = ClipEvidence::new(&root);
    assert!(
        evidence
            .export(
                Path::new("export.zip"),
                &item,
                &clips,
                EXPORTED_AT,
                &runtime()
            )
            .is_err()
    );
    let tar = dir.path().join("export.tar");
    assert!(
        evidence
            .export(&tar, &item, &clips, EXPORTED_AT, &runtime())
            .is_err()
    );
    assert!(!tar.exists());
}

#[test]
fn audio_outside_the_root_is_refused_and_leaves_no_archive() {
    let (dir, root, item, mut clips) = scene();
    let outside = dir.path().join("outside.wav");
    fs::write(&outside, b"RIFF").unwrap();
    clips[0]["audio_path"] = json!(outside.to_str().unwrap());
    let out = dir.path().join("export.zip");
    assert!(
        ClipEvidence::new(&root)
            .export(&out, &item, &clips, EXPORTED_AT, &runtime())
            .is_err()
    );
    assert!(!out.exists());
}

#[test]
fn a_symbolic_link_in_place_of_an_evidence_file_is_not_exported() {
    let (dir, root, item, clips) = scene();
    let secret = dir.path().join("secret.txt");
    fs::write(&secret, b"secret").unwrap();
    fs::remove_file(root.join("full/model.json")).unwrap();
    symlink(&secret, root.join("full/model.json")).unwrap();
    let out = dir.path().join("export.zip");
    ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    let rust = entries(&out);
    assert!(rust.iter().all(|(name, _)| name != "clips/full/model.json"));
    assert!(rust.iter().all(|(_, bytes)| bytes != b"secret"));
}

#[test]
fn a_symbolic_link_in_place_of_the_audio_counts_as_missing() {
    let (dir, root, item, clips) = scene();
    let audio = root.join("full/full.wav");
    let moved = root.join("full/real.wav");
    fs::rename(&audio, &moved).unwrap();
    symlink(&moved, &audio).unwrap();
    let out = dir.path().join("export.zip");
    let report = ClipEvidence::new(&root)
        .export(&out, &item, &clips, EXPORTED_AT, &runtime())
        .unwrap();
    assert!(
        report
            .warnings
            .contains(&"full: cached audio is missing".to_owned())
    );
    assert!(
        entries(&out)
            .iter()
            .all(|(name, _)| name != "clips/full/audio.wav")
    );
}
