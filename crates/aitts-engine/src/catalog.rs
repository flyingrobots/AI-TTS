// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! This module owns the catalog of worker models and their pinned file digests.
//!
//! The digests are the same file the Python setup reads, so the two daemons
//! cannot pin different bytes.

use std::collections::BTreeMap;

/// The models that run in a Python worker process.
pub const WORKER_MODELS: [&str; 3] = ["kokoro", "kokoro-mlx", "chatterbox"];

/// The worker protocol version this crate speaks.
pub const WORKER_PROTOCOL_VERSION: u64 = 2;

const DIGESTS: &str = include_str!("../../../src/aitts/model_digests.json");

/// Why the pinned digests are not available for a model.
#[derive(Debug, PartialEq, Eq)]
pub enum CatalogError {
    UnknownModel,
    InvalidDigestFile,
}

/// The pinned SHA-256 (lowercase hex) of each file that `model` installs.
///
/// # Errors
/// The model is not in the catalog, or the digest file is malformed.
pub fn pinned_digests(model: &str) -> Result<BTreeMap<String, String>, CatalogError> {
    if !WORKER_MODELS.contains(&model) {
        return Err(CatalogError::UnknownModel);
    }
    let all: serde_json::Value =
        serde_json::from_str(DIGESTS).map_err(|_| CatalogError::InvalidDigestFile)?;
    let files = all
        .get(model)
        .and_then(serde_json::Value::as_object)
        .ok_or(CatalogError::InvalidDigestFile)?;
    let mut pins = BTreeMap::new();
    for (file, digest) in files {
        let digest = digest.as_str().filter(|d| is_sha256_hex(d));
        pins.insert(
            file.clone(),
            digest.ok_or(CatalogError::InvalidDigestFile)?.to_owned(),
        );
    }
    if pins.is_empty() {
        return Err(CatalogError::InvalidDigestFile);
    }
    Ok(pins)
}

fn is_sha256_hex(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[cfg(test)]
mod tests {
    //! Size: small. Oracle: `src/aitts/model_digests.json`, the Python setup's pins.
    use super::{CatalogError, WORKER_MODELS, pinned_digests};

    #[test]
    fn every_worker_model_has_well_formed_pins() {
        for model in WORKER_MODELS {
            let pins = pinned_digests(model);
            assert!(pins.is_ok_and(|p| !p.is_empty()), "{model}");
        }
        assert_eq!(pinned_digests("remote"), Err(CatalogError::UnknownModel));
    }
}
