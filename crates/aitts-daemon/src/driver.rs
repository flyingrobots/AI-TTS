// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the loop that drives synthesis ahead of playback.
//!
//! One driver thread asks the conductor for the next clip to synthesize, runs
//! [`crate::synthesis::synthesize`], and plays every device transfer the
//! conductor plans through a [`Sink`]. It sleeps on a wake signal that the API
//! thread sends after each request, and ends when the daemon stops.

use std::path::PathBuf;
use std::sync::mpsc::Receiver;
use std::thread::JoinHandle;

use aitts_artifacts::spool::Spool;
use aitts_engine::registry::Registry;

use crate::conductor::mailbox::Mailbox;

/// An audio output. It owns the device while `play` runs.
pub trait Sink: Send {
    /// Play `spool` for clip `id` to its end.
    ///
    /// # Errors
    /// Returns a description of the device failure; the clip is then failed.
    fn play(&mut self, id: &str, spool: Spool) -> Result<(), String>;
}

/// A sink that reads every frame and discards it, for daemons without a device.
#[derive(Debug, Default)]
pub struct DiscardingSink;

impl Sink for DiscardingSink {
    fn play(&mut self, id: &str, spool: Spool) -> Result<(), String> {
        drop((id.len(), spool));
        Ok(())
    }
}

/// What the driver needs to synthesize and play.
pub struct Synthesis {
    /// The engines clips may name.
    pub engines: Registry,
    /// The directory that holds each clip's spool, `<id>.wav`.
    pub spool_dir: PathBuf,
    /// Frames each spool's read ring holds.
    pub capacity_frames: usize,
    /// The audio output.
    pub sink: Box<dyn Sink>,
}

impl std::fmt::Debug for Synthesis {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Synthesis")
            .field("spool_dir", &self.spool_dir)
            .finish_non_exhaustive()
    }
}

/// Start the driver thread over its own store connection at `database`.
pub(crate) fn spawn(
    synthesis: Synthesis,
    database: PathBuf,
    mailbox: Mailbox,
    wake: Receiver<()>,
) -> std::io::Result<JoinHandle<()>> {
    std::thread::Builder::new()
        .name("ai-ttsd-driver".to_owned())
        .spawn(move || {
            // Stub: wait for the daemon to stop and do nothing.
            drop((synthesis, database, mailbox));
            while wake.recv().is_ok() {}
        })
}
