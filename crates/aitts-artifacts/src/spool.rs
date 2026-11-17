// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The audio spool: a WAV file on disk behind a bounded in-memory ring.
//!
//! This is the Rust form of `aitts.streaming.SpoolingPCMStream`. The format is
//! signed little-endian 16-bit mono PCM at 24 kHz. [`Spool::append`] writes each
//! engine chunk to the file and, when the reader is level with the live end, to
//! the ring. [`Spool::read`] reads only the ring. [`Spool::fill`] moves spooled
//! bytes from the file into the ring after an overflow or a seek; the owner calls
//! it from its feeder thread. The type does no locking: the owner holds it in a
//! mutex, as the Python stream holds its condition.

use std::collections::VecDeque;
use std::fs::File;
use std::io;
use std::path::Path;

/// Samples per second.
pub const SAMPLE_RATE: u32 = 24_000;
/// Bytes per sample.
pub const FRAME_BYTES: usize = 2;

/// The result of one [`Spool::read`]. Silence is never source progress.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpoolRead {
    /// The samples read; empty on an underflow.
    pub pcm: Vec<u8>,
    /// The reader position in frames after this read.
    pub position_frames: u64,
    /// The owner called `finish` and every sample was read.
    pub ended: bool,
    /// The generation or spool error, if any.
    pub error: Option<String>,
    /// Nothing more is coming and every sample was read.
    pub complete: bool,
}

/// One spooled audio stream.
#[derive(Debug)]
pub struct Spool {
    file: File,
    ring: VecDeque<u8>,
    capacity_frames: usize,
}

impl Spool {
    /// Create (or truncate) an owner-only WAV at `path` for live production.
    ///
    /// # Errors
    /// Fails when `path` is a symbolic link, `capacity_frames` is zero, or on an I/O error.
    pub fn create(path: &Path, capacity_frames: usize) -> io::Result<Self> {
        let _ = (path, capacity_frames);
        Err(io::Error::other("not implemented"))
    }

    /// Open a finished WAV for playback without changing its bytes.
    ///
    /// # Errors
    /// Fails when the file is not mono 16-bit 24 kHz PCM, or on an I/O error.
    pub fn open_cached(path: &Path, capacity_frames: usize) -> io::Result<Self> {
        let _ = (path, capacity_frames);
        Err(io::Error::other("not implemented"))
    }

    /// Write one engine chunk. Never waits for the reader or for ring space.
    ///
    /// # Errors
    /// Fails on a half sample, after `seal`, or on an I/O error.
    pub fn append(&mut self, pcm: &[u8]) -> io::Result<()> {
        let _ = pcm;
        Err(io::Error::other("not implemented"))
    }

    /// Move spooled samples from the file into free ring space. Returns the frames moved.
    ///
    /// A read error is recorded and returned by later reads.
    pub fn fill(&mut self) -> usize {
        0
    }

    /// Read up to `frames` samples from the ring only.
    pub fn read(&mut self, frames: usize) -> SpoolRead {
        let _ = (frames, &self.file, &mut self.ring);
        SpoolRead {
            pcm: Vec::new(),
            position_frames: 0,
            ended: false,
            error: None,
            complete: false,
        }
    }

    /// Move the reader to `position_frames`. Does not move or block production.
    pub fn seek(&mut self, position_frames: u64) {
        let _ = position_frames;
    }

    /// Write the final WAV header and return the duration in milliseconds.
    ///
    /// # Errors
    /// Fails on an I/O error.
    pub fn seal(&mut self) -> io::Result<u64> {
        Err(io::Error::other("not implemented"))
    }

    /// Mark the audio published (or failed). Reads may then report `ended`.
    pub fn finish(&mut self, error: Option<String>) {
        drop(error);
    }

    /// The frames now in the ring. Never more than the capacity.
    pub fn buffered_frames(&self) -> usize {
        self.capacity_frames
    }
}
