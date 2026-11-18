// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small (in-memory storage double). Contract: the `Spool` API when the
//! disk fills. The double is a byte vector with a fixed capacity that fails a
//! write past it with `ENOSPC`, as a full file system does (POSIX `write(2)`).
//! Promise: a failed append delivers no unwritten samples to the reader, and
//! the sealed header never claims samples that are not stored.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::io;
use std::sync::{Arc, Mutex};

use aitts_artifacts::spool::{Spool, SpoolStorage};

/// Header (44 bytes) plus two samples fit; anything past `limit` fails.
#[derive(Debug, Clone)]
struct FullDisk {
    bytes: Arc<Mutex<Vec<u8>>>,
    limit: usize,
}

impl FullDisk {
    fn new(limit: usize) -> Self {
        Self {
            bytes: Arc::new(Mutex::new(Vec::new())),
            limit,
        }
    }
}

impl SpoolStorage for FullDisk {
    fn write_all_at(&mut self, buf: &[u8], offset: u64) -> io::Result<()> {
        let start = usize::try_from(offset).unwrap();
        let end = start + buf.len();
        if end > self.limit {
            return Err(io::Error::from_raw_os_error(libc::ENOSPC));
        }
        let mut bytes = self.bytes.lock().unwrap();
        if bytes.len() < end {
            bytes.resize(end, 0);
        }
        bytes[start..end].copy_from_slice(buf);
        Ok(())
    }

    fn read_exact_at(&self, buf: &mut [u8], offset: u64) -> io::Result<()> {
        let bytes = self.bytes.lock().unwrap();
        let start = usize::try_from(offset).unwrap();
        let source = bytes
            .get(start..start + buf.len())
            .ok_or(io::ErrorKind::UnexpectedEof)?;
        buf.copy_from_slice(source);
        Ok(())
    }
}

#[test]
fn an_append_on_a_full_disk_fails_as_storage_full() {
    let disk = FullDisk::new(44 + 4);
    let mut spool = Spool::with_storage(Box::new(disk), 16).unwrap();
    spool.append(&[1, 0, 2, 0]).unwrap();
    let error = spool.append(&[3, 0]).unwrap_err();
    assert_eq!(error.kind(), io::ErrorKind::StorageFull);
}

#[test]
fn a_failed_append_delivers_no_unwritten_samples_to_the_reader() {
    let disk = FullDisk::new(44 + 4);
    let mut spool = Spool::with_storage(Box::new(disk), 16).unwrap();
    spool.append(&[1, 0, 2, 0]).unwrap();
    spool.append(&[3, 0, 4, 0]).unwrap_err();
    spool.fill();
    let read = spool.read(16);
    assert_eq!(read.pcm, [1, 0, 2, 0]);
    assert_eq!(read.position_frames, 2);
}

#[test]
fn the_sealed_header_claims_only_the_stored_samples_after_a_full_disk() {
    let disk = FullDisk::new(44 + 4);
    let stored = Arc::clone(&disk.bytes);
    let mut spool = Spool::with_storage(Box::new(disk), 16).unwrap();
    spool.append(&[1, 0, 2, 0]).unwrap();
    spool.append(&[3, 0, 4, 0]).unwrap_err();
    spool.seal().unwrap();
    let bytes = stored.lock().unwrap();
    // RIFF: bytes 40..44 are the `data` chunk size.
    assert_eq!(u32::from_le_bytes(bytes[40..44].try_into().unwrap()), 4);
    assert_eq!(bytes.len(), 48);
}

#[test]
fn a_full_disk_failure_reaches_the_reader_after_finish() {
    let disk = FullDisk::new(44);
    let mut spool = Spool::with_storage(Box::new(disk), 16).unwrap();
    let error = spool.append(&[1, 0]).unwrap_err();
    spool.finish(Some(error.to_string()));
    let read = spool.read(1);
    assert!(read.ended && read.error.is_some(), "{read:?}");
}
