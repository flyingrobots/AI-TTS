// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the boundary between private text and remote engines.

use core::fmt;

/// The text's immutable disclosure policy.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Sensitivity {
    /// Text may leave this machine.
    Public,
    /// Text must remain on this machine.
    Internal,
    /// Confidential text must remain on this machine.
    Confidential,
}

/// The engine's declared execution boundary, supplied by its adapter.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EngineLocality {
    /// The adapter guarantees synthesis stays on this machine.
    Local,
    /// Synthesis can send text off this machine.
    Remote,
}

/// A policy refusal. It carries no text, engine endpoint, or credentials.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RemoteTextRefused {
    /// The disclosure policy which requires local synthesis.
    pub sensitivity: Sensitivity,
}

impl fmt::Display for RemoteTextRefused {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "remote engine cannot accept {:?} text",
            self.sensitivity
        )
    }
}

impl core::error::Error for RemoteTextRefused {}

/// Admit text to an engine under the same disclosure rule as the Python engine filter.
///
/// # Errors
/// Refuses internal or confidential text when the engine is remote.
pub const fn admit(
    sensitivity: Sensitivity,
    locality: EngineLocality,
) -> Result<(), RemoteTextRefused> {
    match sensitivity {
        Sensitivity::Public => Ok(()),
        Sensitivity::Internal | Sensitivity::Confidential => match locality {
            EngineLocality::Local => Ok(()),
            EngineLocality::Remote => Err(RemoteTextRefused { sensitivity }),
        },
    }
}
