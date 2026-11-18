// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns finding an installed model runtime, as Python
//! `model_setup.installed_runtime`: only a complete manifest that matches the
//! catalog makes a runtime usable. It also holds the catalog facts that
//! decision needs: each model's pinned revision and its voices.

use std::fs;
use std::path::{Path, PathBuf};

use crate::catalog::{WORKER_PROTOCOL_VERSION, pinned_digests};
use crate::engine::{Engine, EngineError, SpeechRequest};

/// Kokoro's voices, in the order of Python `aitts.engines.kokoro.VOICES`.
const KOKORO_VOICES: &[&str] = &[
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "pf_dora",
    "pm_alex",
    "pm_santa",
];

/// The pinned model revision of a catalog model.
pub fn revision(model: &str) -> Option<&'static str> {
    match model {
        "kokoro" => Some("f3ff3571791e39611d31c381e3a41a3af07b4987"),
        "kokoro-mlx" => Some("a71e4d38b236d968966a2002c4c895dbd12b1c3c"),
        "chatterbox" => Some("749d1c1a46eb10492095d68fbcf55691ccf137cd"),
        _ => None,
    }
}

/// The voices a catalog model speaks, in the Python catalog's order.
pub fn voices(model: &str) -> &'static [&'static str] {
    match model {
        "kokoro" | "kokoro-mlx" => KOKORO_VOICES,
        "chatterbox" => &["default"],
        _ => &[],
    }
}

/// The installed runtime root of `model` under `home`, or `None` when no
/// complete, catalog-matching runtime is installed.
///
/// Reads `<home>/model-runtimes/<model>.json`; never follows a symbolic link
/// for the manifest or the runtime root.
pub fn runtime(home: &Path, model: &str) -> Option<PathBuf> {
    let runtimes = home.join("model-runtimes");
    let manifest = runtimes.join(format!("{model}.json"));
    if fs::symlink_metadata(&manifest)
        .ok()?
        .file_type()
        .is_symlink()
    {
        return None;
    }
    let payload: serde_json::Value = serde_json::from_slice(&fs::read(&manifest).ok()?).ok()?;
    let directory = payload.get("directory")?.as_str()?;
    let matches = payload.get("revision").and_then(serde_json::Value::as_str) == revision(model)
        && payload
            .get("worker_protocol")
            .and_then(serde_json::Value::as_u64)
            == Some(WORKER_PROTOCOL_VERSION)
        && directory.starts_with(&format!("{model}-"))
        && Path::new(directory)
            .file_name()
            .and_then(|name| name.to_str())
            == Some(directory);
    if !matches {
        return None;
    }
    let root = runtimes.join(directory);
    let complete = !fs::symlink_metadata(&root).ok()?.file_type().is_symlink()
        && root.join("venv/bin/python").is_file()
        && root.join("adapter/aitts/model_worker.py").is_file()
        && pinned_digests(model)
            .ok()?
            .keys()
            .all(|file| root.join("assets").join(file).is_file());
    complete.then_some(root)
}

/// A catalog model with no installed runtime: listed, but every request fails
/// with the model-setup instruction, as Python's managed engine does.
#[derive(Debug)]
pub struct NotInstalled {
    name: &'static str,
}

impl NotInstalled {
    /// Stand in for the catalog model `name`.
    pub const fn new(name: &'static str) -> Self {
        Self { name }
    }
}

impl Engine for NotInstalled {
    fn name(&self) -> &str {
        self.name
    }

    fn stream(
        &mut self,
        _request: &SpeechRequest<'_>,
        _sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        Err(EngineError::Refused(
            "the model is not installed; run `ai-tts model-setup`",
        ))
    }
}
