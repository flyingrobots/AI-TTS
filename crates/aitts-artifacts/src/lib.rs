// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Generated audio files and their private directories, in the Python layout.
//!
//! [`private_fs`] creates and checks owner-only files and directories without
//! following symbolic links, as `aitts.adapters.private_files` does.
//! [`audio::AudioArtifacts`] writes each synthesized WAV to a hidden candidate
//! and publishes it with one atomic rename, as
//! `aitts.adapters.audio_artifacts.FileAudioArtifacts` does.

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

pub mod audio;
pub mod evidence;
pub mod private_fs;
pub mod records;
pub mod spool;
mod wav;
