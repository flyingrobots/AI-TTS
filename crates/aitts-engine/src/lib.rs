// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! AI-TTS speech engines for the Rust daemon.
//!
//! This crate owns how the daemon reaches a speech model: the [`engine::Engine`]
//! interface, the [`registry::Registry`] of named engines, the
//! [`worker::WorkerSupervisor`] that runs one Python model worker over the binary
//! frame protocol, the [`loopback_http::LoopbackHttpEngine`] for a separately
//! managed local server, the pinned model [`catalog`], and [`setup`] digest checks.

pub mod catalog;
pub mod engine;
pub mod loopback_http;
pub mod registry;
pub mod setup;
pub mod worker;
