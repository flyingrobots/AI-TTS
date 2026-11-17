// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Small tests of owner-only files and directories.
//! Oracle: `aitts.adapters.private_files` and `tests/test_private_state_permissions.py`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::Path;
use std::process::Command;

use aitts_artifacts::private_fs::{
    create_private_file, ensure_private_directory, ensure_private_file, secure_existing_file,
};

fn mode(path: &Path) -> u32 {
    fs::symlink_metadata(path).unwrap().permissions().mode() & 0o777
}

#[test]
fn new_directories_and_files_are_owner_only() {
    let home = tempfile::tempdir().unwrap();
    let directory = home.path().join("cache");
    ensure_private_directory(&directory, true).unwrap();
    let file = directory.join("state.db");
    ensure_private_file(&file).unwrap();
    let created = directory.join("new.wav");
    create_private_file(&created).unwrap();
    assert_eq!(mode(&directory), 0o700);
    assert_eq!(mode(&file), 0o600);
    assert_eq!(mode(&created), 0o600);
}

#[test]
fn existing_permissive_paths_are_narrowed() {
    let home = tempfile::tempdir().unwrap();
    let directory = home.path().join("cache");
    fs::create_dir(&directory).unwrap();
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o755)).unwrap();
    let file = directory.join("clip.wav");
    fs::write(&file, b"RIFF").unwrap();
    fs::set_permissions(&file, fs::Permissions::from_mode(0o644)).unwrap();
    ensure_private_directory(&directory, true).unwrap();
    assert!(secure_existing_file(&file).unwrap());
    assert_eq!(mode(&directory), 0o700);
    assert_eq!(mode(&file), 0o600);
    assert!(!secure_existing_file(&directory.join("absent")).unwrap());
}

#[test]
fn a_symbolic_link_in_place_of_a_file_or_directory_is_refused() {
    let home = tempfile::tempdir().unwrap();
    let outside = home.path().join("outside");
    fs::create_dir(&outside).unwrap();
    fs::set_permissions(&outside, fs::Permissions::from_mode(0o755)).unwrap();
    let target = outside.join("victim");
    fs::write(&target, b"x").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o644)).unwrap();
    let linked_dir = home.path().join("linked-dir");
    symlink(&outside, &linked_dir).unwrap();
    let linked_file = home.path().join("linked-file");
    symlink(&target, &linked_file).unwrap();

    assert!(ensure_private_directory(&linked_dir, true).is_err());
    assert!(ensure_private_file(&linked_file).is_err());
    assert!(secure_existing_file(&linked_file).is_err());
    assert_eq!(mode(&outside), 0o755);
    assert_eq!(mode(&target), 0o644);
}

#[test]
fn a_fifo_in_place_of_a_file_is_refused_without_blocking() {
    let home = tempfile::tempdir().unwrap();
    let fifo = home.path().join("state.db");
    assert!(
        Command::new("mkfifo")
            .arg(&fifo)
            .status()
            .unwrap()
            .success()
    );
    let (sender, receiver) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let refused = ensure_private_file(&fifo).is_err() && secure_existing_file(&fifo).is_err();
        sender.send(refused).unwrap();
    });
    let refused = receiver.recv_timeout(std::time::Duration::from_secs(5));
    assert_eq!(refused, Ok(true), "a FIFO must be refused at once");
}

#[test]
fn create_refuses_an_existing_file() {
    let home = tempfile::tempdir().unwrap();
    let file = home.path().join("clip.wav");
    fs::write(&file, b"kept").unwrap();
    assert!(create_private_file(&file).is_err());
    assert_eq!(fs::read(&file).unwrap(), b"kept");
}
