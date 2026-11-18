// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns finding an installed model runtime, as Python
//! `model_setup.installed_runtime`: only a complete manifest that matches the
//! catalog makes a runtime usable.

use std::path::{Path, PathBuf};

/// The pinned model revision of a catalog model.
pub fn revision(_model: &str) -> Option<&'static str> {
    None
}

/// The voices a catalog model speaks, in the Python catalog's order.
pub fn voices(_model: &str) -> &'static [&'static str] {
    &[]
}

/// The installed runtime root of `model` under `home`, or `None` when no
/// complete, catalog-matching runtime is installed.
pub fn runtime(_home: &Path, _model: &str) -> Option<PathBuf> {
    None
}
