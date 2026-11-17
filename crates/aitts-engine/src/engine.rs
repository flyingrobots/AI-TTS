// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! This module owns the engine interface and its typed, content-free errors.

use std::fmt;

/// One speech request. Text never appears in an error.
#[derive(Debug, Clone, Copy)]
pub struct SpeechRequest<'a> {
    pub text: &'a str,
    pub voice: &'a str,
    pub speed: f64,
}

/// A speech engine. A failed stream returns `Err`: audio already given to the
/// sink is then a partial clip and the caller must discard it.
pub trait Engine: Send {
    /// The catalog or configured name of this engine.
    fn name(&self) -> &str;

    /// Render `request`, giving each audio block to `sink` as it arrives.
    ///
    /// # Errors
    /// Any failure of the engine, its worker or its server.
    fn stream(
        &mut self,
        request: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError>;
}

/// Why an engine refused or failed a request.
#[derive(Debug)]
pub enum EngineError {
    /// The configuration is not usable, for example a remote URL.
    Refused(&'static str),
    /// The worker speaks another protocol version.
    Protocol,
    /// The worker or server gave no reply in the time limit; it was stopped.
    Timeout,
    /// The worker exited; restart it to continue.
    WorkerExited,
    /// The worker or server sent bytes that break the protocol.
    InvalidResponse(&'static str),
    /// The model reported a failure.
    ModelFailed,
    /// An operating-system call failed.
    Io(std::io::Error),
}

impl fmt::Display for EngineError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Refused(why) => write!(f, "engine refused: {why}"),
            Self::Protocol => {
                f.write_str("model worker speaks another protocol; refresh model setup")
            }
            Self::Timeout => f.write_str("model worker timed out and was stopped"),
            Self::WorkerExited => f.write_str("model worker stopped; restart the model"),
            Self::InvalidResponse(why) => write!(f, "model returned an invalid response: {why}"),
            Self::ModelFailed => f.write_str("model could not render audio"),
            Self::Io(error) => write!(f, "engine I/O failed: {error}"),
        }
    }
}

impl std::error::Error for EngineError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            _ => None,
        }
    }
}

impl From<std::io::Error> for EngineError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}
