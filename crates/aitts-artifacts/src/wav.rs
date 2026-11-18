// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The RIFF/WAVE header fields that the spool and the audio record read.

use std::fs::File;
use std::io::{self, ErrorKind};
use std::os::unix::fs::FileExt;

/// The format and data location of one WAV file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct WavFormat {
    /// 1 for integer PCM, 3 for IEEE float (resolved through `WAVE_FORMAT_EXTENSIBLE`).
    pub(crate) format_tag: u16,
    pub(crate) channels: u16,
    pub(crate) sample_rate: u32,
    pub(crate) bits_per_sample: u16,
    pub(crate) block_align: u16,
    pub(crate) data_offset: u64,
    pub(crate) data_bytes: u64,
}

const EXTENSIBLE: u16 = 0xFFFE;

/// Walk the RIFF chunks to the `fmt ` and `data` chunks.
pub(crate) fn read_format(file: &File) -> io::Result<WavFormat> {
    let not_wav = || io::Error::new(ErrorKind::InvalidData, "not a RIFF/WAVE file");
    let mut riff = [0u8; 12];
    file.read_exact_at(&mut riff, 0).map_err(|_| not_wav())?;
    if riff.get(..4) != Some(b"RIFF") || riff.get(8..) != Some(b"WAVE") {
        return Err(not_wav());
    }
    let mut offset = 12u64;
    let mut format: Option<[u16; 4]> = None;
    let mut sample_rate = 0;
    loop {
        let mut chunk = [0u8; 8];
        file.read_exact_at(&mut chunk, offset)
            .map_err(|_| not_wav())?;
        let [i0, i1, i2, i3, s0, s1, s2, s3] = chunk;
        let size = u64::from(u32::from_le_bytes([s0, s1, s2, s3]));
        let body = offset.checked_add(8).ok_or_else(not_wav)?;
        match &[i0, i1, i2, i3] {
            b"fmt " => {
                let mut fmt = [0u8; 26];
                let wanted = if size >= 26 { 26 } else { 16 };
                let fmt_part = fmt.get_mut(..wanted).ok_or_else(not_wav)?;
                file.read_exact_at(fmt_part, body).map_err(|_| not_wav())?;
                let [
                    f0,
                    f1,
                    c0,
                    c1,
                    r0,
                    r1,
                    r2,
                    r3,
                    _,
                    _,
                    _,
                    _,
                    a0,
                    a1,
                    b0,
                    b1,
                    ..,
                ] = fmt;
                let [.., g0, g1] = fmt;
                let mut tag = u16::from_le_bytes([f0, f1]);
                if tag == EXTENSIBLE {
                    tag = u16::from_le_bytes([g0, g1]);
                }
                sample_rate = u32::from_le_bytes([r0, r1, r2, r3]);
                format = Some([
                    tag,
                    u16::from_le_bytes([c0, c1]),
                    u16::from_le_bytes([b0, b1]),
                    u16::from_le_bytes([a0, a1]),
                ]);
            }
            b"data" => {
                let [format_tag, channels, bits_per_sample, block_align] =
                    format.ok_or_else(not_wav)?;
                return Ok(WavFormat {
                    format_tag,
                    channels,
                    sample_rate,
                    bits_per_sample,
                    block_align,
                    data_offset: body,
                    data_bytes: size,
                });
            }
            _ => {}
        }
        // Chunks are padded to an even length.
        offset = body
            .checked_add(size)
            .and_then(|end| end.checked_add(size % 2))
            .ok_or_else(not_wav)?;
    }
}
