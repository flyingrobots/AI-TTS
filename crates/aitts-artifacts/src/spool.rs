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
use std::fs::{File, OpenOptions, Permissions};
use std::io::{self, ErrorKind};
use std::os::unix::fs::{FileExt, OpenOptionsExt, PermissionsExt};
use std::path::Path;

use crate::private_fs::PRIVATE_FILE_MODE;
use crate::wav::read_format;

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

/// The length of the canonical header that Python's `wave` module writes.
const HEADER_BYTES: u64 = 44;

/// Positional storage behind a spool: a file, or a test double at this seam.
pub trait SpoolStorage: Send + std::fmt::Debug {
    /// Write all of `buf` at `offset`.
    ///
    /// # Errors
    /// An I/O error, such as `StorageFull` when the disk is full.
    fn write_all_at(&mut self, buf: &[u8], offset: u64) -> io::Result<()>;
    /// Fill `buf` from `offset`.
    ///
    /// # Errors
    /// An I/O error, or `UnexpectedEof` when fewer bytes are stored.
    fn read_exact_at(&self, buf: &mut [u8], offset: u64) -> io::Result<()>;
}

impl SpoolStorage for File {
    fn write_all_at(&mut self, buf: &[u8], offset: u64) -> io::Result<()> {
        FileExt::write_all_at(self, buf, offset)
    }
    fn read_exact_at(&self, buf: &mut [u8], offset: u64) -> io::Result<()> {
        FileExt::read_exact_at(self, buf, offset)
    }
}

/// One spooled audio stream.
#[derive(Debug)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "the four flags are the Python stream's independent states"
)]
pub struct Spool {
    file: Box<dyn SpoolStorage>,
    data_offset: u64,
    ring: VecDeque<u8>,
    capacity_frames: usize,
    available: u64,
    fed: u64,
    position: u64,
    sealed: bool,
    finished: bool,
    error: Option<String>,
}

impl Spool {
    /// Create (or truncate) an owner-only WAV at `path` for live production.
    ///
    /// # Errors
    /// Fails when `path` is a symbolic link, `capacity_frames` is zero, or on an I/O error.
    pub fn create(path: &Path, capacity_frames: usize) -> io::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .mode(PRIVATE_FILE_MODE)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?;
        file.set_permissions(Permissions::from_mode(PRIVATE_FILE_MODE))?;
        file.write_all_at(&header(0), 0)?;
        Self::new(Box::new(file), HEADER_BYTES, 0, false, capacity_frames)
    }

    /// Start a live spool on `storage` instead of a file.
    ///
    /// # Errors
    /// Fails when `capacity_frames` is zero or the header cannot be written.
    pub fn with_storage(
        storage: Box<dyn SpoolStorage>,
        capacity_frames: usize,
    ) -> io::Result<Self> {
        let mut storage = storage;
        storage.write_all_at(&header(0), 0)?;
        Self::new(storage, HEADER_BYTES, 0, false, capacity_frames)
    }

    /// Open a finished WAV for playback without changing its bytes.
    ///
    /// # Errors
    /// Fails when the file is not mono 16-bit 24 kHz PCM, or on an I/O error.
    pub fn open_cached(path: &Path, capacity_frames: usize) -> io::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?;
        let (data_offset, data_bytes) = find_pcm_data(&file)?;
        let frames = data_bytes / frame_bytes();
        Self::new(Box::new(file), data_offset, frames, true, capacity_frames)
    }

    fn new(
        file: Box<dyn SpoolStorage>,
        data_offset: u64,
        available: u64,
        cached: bool,
        capacity_frames: usize,
    ) -> io::Result<Self> {
        if capacity_frames == 0 {
            return Err(invalid("PCM buffer capacity must be positive"));
        }
        Ok(Self {
            file,
            data_offset,
            ring: VecDeque::with_capacity(capacity_frames.saturating_mul(FRAME_BYTES)),
            capacity_frames,
            available,
            fed: 0,
            position: 0,
            sealed: cached,
            finished: cached,
            error: None,
        })
    }

    /// Write one engine chunk. Never waits for the reader or for ring space.
    ///
    /// # Errors
    /// Fails on a half sample, after `seal`, or on an I/O error.
    pub fn append(&mut self, pcm: &[u8]) -> io::Result<()> {
        if !pcm.len().is_multiple_of(FRAME_BYTES) {
            return Err(invalid("PCM chunks must contain whole 16-bit samples"));
        }
        if self.sealed {
            return Err(invalid("PCM production is closed"));
        }
        self.file
            .write_all_at(pcm, self.data_offset + self.available * frame_bytes())?;
        let prior_end = self.available;
        self.available += to_u64(pcm.len()) / frame_bytes();
        // The live path goes straight into the ring; overflow stays in the file.
        if self.fed == prior_end {
            let take = (pcm.len() / FRAME_BYTES).min(self.free_frames());
            self.ring
                .extend(pcm.iter().take(take * FRAME_BYTES).copied());
            self.fed += to_u64(take);
        }
        Ok(())
    }

    /// Move spooled samples from the file into free ring space. Returns the frames moved.
    ///
    /// A read error is recorded and returned by later reads.
    pub fn fill(&mut self) -> usize {
        if self.error.is_some() || self.fed >= self.available {
            return 0;
        }
        let pending = usize::try_from(self.available - self.fed).unwrap_or(usize::MAX);
        let count = pending.min(self.free_frames());
        let mut pcm = vec![0; count * FRAME_BYTES];
        let offset = self.data_offset + self.fed * frame_bytes();
        if let Err(error) = self.file.read_exact_at(&mut pcm, offset) {
            self.error = Some(format!("PCM spool returned incomplete frames: {error}"));
            self.finished = true;
            return 0;
        }
        self.ring.extend(pcm);
        self.fed += to_u64(count);
        count
    }

    /// Read up to `frames` samples from the ring only.
    pub fn read(&mut self, frames: usize) -> SpoolRead {
        let count = frames.min(self.buffered_frames());
        let pcm: Vec<u8> = self.ring.drain(..count * FRAME_BYTES).collect();
        self.position += to_u64(count);
        let drained = self.position >= self.available;
        SpoolRead {
            pcm,
            position_frames: self.position,
            ended: self.finished && drained,
            error: self.error.clone(),
            complete: (self.sealed || self.finished) && drained,
        }
    }

    /// Move the reader to `position_frames`. Does not move or block production.
    pub fn seek(&mut self, position_frames: u64) {
        if position_frames == self.position {
            return;
        }
        self.ring.clear();
        self.position = position_frames;
        self.fed = position_frames;
    }

    /// Write the final WAV header and return the duration in milliseconds.
    ///
    /// # Errors
    /// Fails on an I/O error.
    pub fn seal(&mut self) -> io::Result<u64> {
        if !self.sealed {
            let data_bytes = u32::try_from(self.available * frame_bytes())
                .map_err(|_| invalid("PCM spool exceeds the WAV size limit"))?;
            self.file.write_all_at(&header(data_bytes), 0)?;
            self.sealed = true;
        }
        Ok(self.available * 1000 / u64::from(SAMPLE_RATE))
    }

    /// Mark the audio published (or failed). Reads may then report `ended`.
    pub fn finish(&mut self, error: Option<String>) {
        if error.is_some() {
            self.error = error;
        }
        self.finished = true;
    }

    /// The frames now in the ring. Never more than the capacity.
    pub fn buffered_frames(&self) -> usize {
        self.ring.len() / FRAME_BYTES
    }

    fn free_frames(&self) -> usize {
        self.capacity_frames - self.buffered_frames()
    }
}

fn frame_bytes() -> u64 {
    to_u64(FRAME_BYTES)
}

fn to_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(ErrorKind::InvalidInput, message)
}

/// The canonical 44-byte header, as Python's `wave` module writes it.
fn header(data_bytes: u32) -> Vec<u8> {
    let mut out = Vec::with_capacity(44);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&data_bytes.saturating_add(36).to_le_bytes());
    out.extend_from_slice(b"WAVEfmt ");
    out.extend_from_slice(&16u32.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes()); // PCM
    out.extend_from_slice(&1u16.to_le_bytes()); // mono
    out.extend_from_slice(&SAMPLE_RATE.to_le_bytes());
    out.extend_from_slice(&(SAMPLE_RATE * 2).to_le_bytes());
    out.extend_from_slice(&2u16.to_le_bytes()); // block align
    out.extend_from_slice(&16u16.to_le_bytes()); // bits
    out.extend_from_slice(b"data");
    out.extend_from_slice(&data_bytes.to_le_bytes());
    out
}

/// Return the offset and length of mono 16-bit 24 kHz PCM data.
fn find_pcm_data(file: &File) -> io::Result<(u64, u64)> {
    let not_pcm = || invalid("cached WAV is not streaming PCM");
    let format = read_format(file).map_err(|_| not_pcm())?;
    let streaming = format.format_tag == 1
        && format.channels == 1
        && format.sample_rate == SAMPLE_RATE
        && format.bits_per_sample == 16;
    if !streaming {
        return Err(not_pcm());
    }
    Ok((format.data_offset, format.data_bytes))
}
