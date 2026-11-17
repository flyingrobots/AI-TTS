// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files). Oracle: FIPS 180-4 SHA-256 of "abc"
//! and issue #133: setup refuses a model file whose digest is not the pinned digest.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

use std::collections::BTreeMap;
use std::fs;
use std::sync::atomic::AtomicBool;

use aitts_engine::setup::{SetupError, verify_files, verify_model_assets};

const ABC: &str = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

fn pins() -> BTreeMap<String, String> {
    BTreeMap::from([("voices/a.pt".to_owned(), ABC.to_owned())])
}

fn assets(content: &[u8]) -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    fs::create_dir(root.path().join("voices")).unwrap();
    fs::write(root.path().join("voices/a.pt"), content).unwrap();
    root
}

#[test]
fn the_pinned_bytes_pass() {
    let root = assets(b"abc");
    assert!(verify_files(root.path(), &pins(), &AtomicBool::new(false)).is_ok());
}

#[test]
fn a_file_with_another_digest_is_refused() {
    let root = assets(b"abd");
    let result = verify_files(root.path(), &pins(), &AtomicBool::new(false));
    assert!(matches!(result, Err(SetupError::DigestMismatch(f)) if f == "voices/a.pt"));
}

#[test]
fn a_missing_or_linked_file_is_refused() {
    let root = assets(b"abc");
    fs::rename(root.path().join("voices/a.pt"), root.path().join("real")).unwrap();
    let cancel = AtomicBool::new(false);
    assert!(matches!(
        verify_files(root.path(), &pins(), &cancel),
        Err(SetupError::Missing(_))
    ));
    std::os::unix::fs::symlink(root.path().join("real"), root.path().join("voices/a.pt")).unwrap();
    assert!(matches!(
        verify_files(root.path(), &pins(), &cancel),
        Err(SetupError::Missing(_))
    ));
}

#[test]
fn a_cancelled_setup_stops_with_cancelled() {
    let root = assets(b"abc");
    let result = verify_files(root.path(), &pins(), &AtomicBool::new(true));
    assert!(matches!(result, Err(SetupError::Cancelled)));
}

#[test]
fn real_model_pins_refuse_an_empty_runtime() {
    let root = tempfile::tempdir().unwrap();
    let cancel = AtomicBool::new(false);
    assert!(matches!(
        verify_model_assets("kokoro", root.path(), &cancel),
        Err(SetupError::Missing(_))
    ));
    assert!(matches!(
        verify_model_assets("remote", root.path(), &cancel),
        Err(SetupError::UnknownModel)
    ));
}
