// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files).
//! Finding an installed model runtime and its catalog facts.
//! Oracles: Python `model_setup.installed_runtime` (read as the specification);
//! the Python catalog sources themselves for revisions
//! (`src/aitts/model_catalog.py`) and Kokoro voices (`src/aitts/engines/kokoro.py`),
//! read as text so the two catalogs cannot drift.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::string_slice,
    reason = "test code fails loudly"
)]

use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

use aitts_engine::catalog::{WORKER_MODELS, WORKER_PROTOCOL_VERSION, pinned_digests};
use aitts_engine::installed::{revision, runtime, voices};

fn python_source(path: &str) -> String {
    fs::read_to_string(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join(path),
    )
    .unwrap()
}

/// The 40-hex revision that follows the quoted model name in `model_catalog.py`.
fn python_revision(model: &str) -> String {
    let source = python_source("src/aitts/model_catalog.py");
    let start = source.find(&format!("\"{model}\",\n")).unwrap();
    source[start..]
        .split('"')
        .find(|part| part.len() == 40 && part.bytes().all(|byte| byte.is_ascii_hexdigit()))
        .unwrap()
        .to_owned()
}

fn python_kokoro_voices() -> Vec<String> {
    let source = python_source("src/aitts/engines/kokoro.py");
    let start = source.find("VOICES: tuple[str, ...] = (").unwrap();
    let body = &source[start..start + source[start..].find("\n)").unwrap()];
    body.lines()
        .map(str::trim)
        .filter(|line| line.starts_with('"'))
        .map(|line| line.trim_end_matches(',').trim_matches('"').to_owned())
        .collect()
}

#[test]
fn every_worker_model_has_the_python_revision() {
    for model in WORKER_MODELS {
        assert_eq!(
            revision(model),
            Some(python_revision(model).as_str()),
            "{model}"
        );
    }
    assert_eq!(revision("unknown"), None);
}

#[test]
fn kokoro_voices_equal_the_python_catalog() {
    let python = python_kokoro_voices();
    assert!(
        python.len() > 20,
        "parsed only {} Python voices",
        python.len()
    );
    assert_eq!(voices("kokoro"), python);
    assert_eq!(voices("chatterbox"), ["default"]);
}

/// A complete kokoro runtime under `home`; returns its root.
fn install(home: &Path, manifest: &serde_json::Value) -> PathBuf {
    let runtimes = home.join("model-runtimes");
    let root = runtimes.join("kokoro-0123");
    fs::create_dir_all(root.join("venv/bin")).unwrap();
    fs::create_dir_all(root.join("adapter/aitts")).unwrap();
    fs::write(root.join("venv/bin/python"), "").unwrap();
    fs::write(root.join("adapter/aitts/model_worker.py"), "").unwrap();
    for file in pinned_digests("kokoro").unwrap().keys() {
        let path = root.join("assets").join(file);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, "").unwrap();
    }
    fs::write(runtimes.join("kokoro.json"), manifest.to_string()).unwrap();
    root
}

fn manifest() -> serde_json::Value {
    serde_json::json!({
        "directory": "kokoro-0123",
        "revision": python_revision("kokoro"),
        "worker_protocol": WORKER_PROTOCOL_VERSION,
    })
}

#[test]
fn a_complete_matching_runtime_is_found() {
    let home = tempfile::tempdir().unwrap();
    let root = install(home.path(), &manifest());
    assert_eq!(runtime(home.path(), "kokoro"), Some(root));
}

#[test]
fn a_runtime_for_another_revision_is_not_used() {
    let home = tempfile::tempdir().unwrap();
    let mut stale = manifest();
    stale["revision"] = "0".repeat(40).into();
    install(home.path(), &stale);
    assert_eq!(runtime(home.path(), "kokoro"), None);
}

#[test]
fn a_runtime_for_another_worker_protocol_is_not_used() {
    let home = tempfile::tempdir().unwrap();
    let mut old = manifest();
    old["worker_protocol"] = 1.into();
    install(home.path(), &old);
    assert_eq!(runtime(home.path(), "kokoro"), None);
}

#[test]
fn a_directory_outside_the_runtimes_folder_is_not_used() {
    let home = tempfile::tempdir().unwrap();
    let mut escaping = manifest();
    // It names the real runtime through a parent step, so only the name
    // check refuses it.
    escaping["directory"] = "kokoro-0123/../kokoro-0123".into();
    install(home.path(), &escaping);
    assert_eq!(runtime(home.path(), "kokoro"), None);
}

#[test]
fn a_runtime_missing_an_asset_is_not_used() {
    let home = tempfile::tempdir().unwrap();
    let root = install(home.path(), &manifest());
    fs::remove_file(root.join("assets/config.json")).unwrap();
    assert_eq!(runtime(home.path(), "kokoro"), None);
}

#[test]
fn a_symbolic_link_manifest_is_not_used() {
    let home = tempfile::tempdir().unwrap();
    install(home.path(), &manifest());
    let runtimes = home.path().join("model-runtimes");
    fs::rename(runtimes.join("kokoro.json"), runtimes.join("real.json")).unwrap();
    symlink(runtimes.join("real.json"), runtimes.join("kokoro.json")).unwrap();
    assert_eq!(runtime(home.path(), "kokoro"), None);
}
