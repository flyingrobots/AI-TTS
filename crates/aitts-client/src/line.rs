// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns bounded newline framing over a connected daemon socket.

#![deny(clippy::arithmetic_side_effects)]

use crate::error::ClientError;
use aitts_protocol::MAX_RESPONSE_BYTES;
use std::io::{self, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

const READ_CHUNK: usize = 64 * 1024;

/// One connection that has sent its request line and reads reply or event lines.
#[derive(Debug)]
pub(crate) struct LineReader {
    stream: UnixStream,
    /// Received bytes not yet returned as a line.
    pending: Vec<u8>,
    /// Leading bytes of `pending` already known to hold no newline.
    scanned: usize,
}

fn stream_error(error: &io::Error) -> ClientError {
    match error.kind() {
        io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut => ClientError::TimedOut,
        kind => ClientError::Io(kind),
    }
}

impl LineReader {
    /// Connect to `socket`, bound each read and write by `limit`, and send `request`.
    pub(crate) fn connect(
        socket: &Path,
        limit: Duration,
        request: &[u8],
    ) -> Result<Self, ClientError> {
        let mut stream =
            UnixStream::connect(socket).map_err(|error| ClientError::Unreachable(error.kind()))?;
        stream
            .set_read_timeout(Some(limit))
            .and_then(|()| stream.set_write_timeout(Some(limit)))
            .map_err(|error| ClientError::Io(error.kind()))?;
        stream
            .write_all(request)
            .map_err(|error| stream_error(&error))?;
        Ok(Self {
            stream,
            pending: Vec::new(),
            scanned: 0,
        })
    }

    /// The next line, including its newline, of at most `MAX_RESPONSE_BYTES`.
    pub(crate) fn next_line(&mut self) -> Result<Vec<u8>, ClientError> {
        let mut chunk = vec![0; READ_CHUNK];
        loop {
            let unscanned = self.pending.get(self.scanned..).unwrap_or_default();
            if let Some(offset) = unscanned.iter().position(|byte| *byte == b'\n') {
                let end = self.scanned.saturating_add(offset).saturating_add(1);
                let rest = self.pending.split_off(end);
                self.scanned = 0;
                return Ok(std::mem::replace(&mut self.pending, rest));
            }
            self.scanned = self.pending.len();
            if self.pending.len() >= MAX_RESPONSE_BYTES {
                return Err(ClientError::Wire(aitts_protocol::WireError::TooLarge));
            }
            match self.stream.read(&mut chunk) {
                Ok(0) => return Err(ClientError::Closed),
                Ok(count) => self
                    .pending
                    .extend_from_slice(chunk.get(..count).unwrap_or_default()),
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) => return Err(stream_error(&error)),
            }
        }
    }
}
