// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Small tests of atomic audio publication in the Python layout.
//! Oracle: `aitts.adapters.audio_artifacts.FileAudioArtifacts` and
//! `tests/test_audio_artifacts.py`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use std::fs;
use std::io::Write as _;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::Path;

use aitts_artifacts::audio::AudioArtifacts;

fn mode(path: &Path) -> u32 {
    fs::symlink_metadata(path).unwrap().permissions().mode() & 0o777
}

#[test]
fn candidate_and_published_paths_use_the_python_layout() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = AudioArtifacts::new(root.path());
    let candidate = artifacts.target("utt_0001").unwrap();
    assert_eq!(candidate, root.path().join("utt_0001/.utt_0001.wav.part"));
    assert_eq!(mode(&candidate), 0o600);
    assert_eq!(mode(&root.path().join("utt_0001")), 0o700);
    fs::write(&candidate, b"RIFF....WAVE").unwrap();
    let published = artifacts.publish("utt_0001", &candidate).unwrap();
    assert_eq!(published, root.path().join("utt_0001/utt_0001.wav"));
    assert_eq!(fs::read(&published).unwrap(), b"RIFF....WAVE");
    assert_eq!(mode(&published), 0o600);
    assert!(!candidate.exists());
}

#[test]
fn a_partial_write_is_never_visible_at_the_published_path() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = AudioArtifacts::new(root.path());
    let first = artifacts.target("utt").unwrap();
    fs::write(&first, b"old complete").unwrap();
    let published = artifacts.publish("utt", &first).unwrap();

    let second = artifacts.target("utt").unwrap();
    let mut writer = fs::OpenOptions::new().write(true).open(&second).unwrap();
    writer.write_all(b"new par").unwrap();
    assert_eq!(fs::read(&published).unwrap(), b"old complete");
    writer.write_all(b"tial done").unwrap();
    drop(writer);
    artifacts.publish("utt", &second).unwrap();
    assert_eq!(fs::read(&published).unwrap(), b"new partial done");
}

#[test]
fn prepare_discards_crash_candidates_and_keeps_published_audio() {
    let root = tempfile::tempdir().unwrap();
    let clip = root.path().join("utt");
    fs::create_dir_all(&clip).unwrap();
    fs::set_permissions(&clip, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(clip.join(".utt.wav.part"), b"half").unwrap();
    fs::write(clip.join("utt.wav"), b"whole").unwrap();
    fs::set_permissions(clip.join("utt.wav"), fs::Permissions::from_mode(0o644)).unwrap();
    fs::write(root.path().join(".loose.wav.part"), b"half").unwrap();

    AudioArtifacts::new(root.path()).prepare().unwrap();

    assert!(!clip.join(".utt.wav.part").exists());
    assert!(!root.path().join(".loose.wav.part").exists());
    assert_eq!(fs::read(clip.join("utt.wav")).unwrap(), b"whole");
    assert_eq!(mode(&clip.join("utt.wav")), 0o600);
    assert_eq!(mode(&clip), 0o700);
}

#[test]
fn prepare_leaves_symbolic_links_and_their_targets_alone() {
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let target = outside.path().join("victim.wav");
    fs::write(&target, b"x").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o644)).unwrap();
    symlink(&target, root.path().join("link.wav")).unwrap();
    symlink(outside.path(), root.path().join("linkdir")).unwrap();
    AudioArtifacts::new(root.path()).prepare().unwrap();
    assert_eq!(mode(&target), 0o644);
    assert!(target.exists());
}

#[test]
fn identities_that_escape_the_root_are_refused() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = AudioArtifacts::new(root.path());
    for id in ["", ".", "..", "a/b", "../x"] {
        assert!(artifacts.target(id).is_err(), "{id:?}");
    }
    let candidate = artifacts.target("utt").unwrap();
    artifacts.target("other").unwrap();
    assert!(artifacts.publish("other", &candidate).is_err());
    assert!(candidate.exists());
}

#[test]
fn only_a_non_empty_regular_file_is_usable() {
    let root = tempfile::tempdir().unwrap();
    let empty = root.path().join("empty.wav");
    fs::write(&empty, b"").unwrap();
    let full = root.path().join("full.wav");
    fs::write(&full, b"RIFF").unwrap();
    let link = root.path().join("link.wav");
    symlink(&full, &link).unwrap();
    assert!(AudioArtifacts::is_usable(&full));
    assert!(!AudioArtifacts::is_usable(&empty));
    assert!(!AudioArtifacts::is_usable(&link));
    assert!(!AudioArtifacts::is_usable(root.path()));
    assert!(AudioArtifacts::discard(&full));
    assert!(AudioArtifacts::discard(&full));
    assert!(!full.exists());
}
