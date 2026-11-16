// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Pure domain rules for AI-TTS. Callers supply all external observations.
//!
//! This crate does not access devices, persistence, clocks, or other I/O.

#![no_std]
#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

extern crate alloc;

pub mod plan;
pub mod retention;
pub mod segmentation;
pub mod sensitivity;
pub mod settings;
pub mod utterance;
pub mod voices;

mod allocation;
pub use allocation::{CollectionLimit, MAX_COLLECTION_ENTRIES};
