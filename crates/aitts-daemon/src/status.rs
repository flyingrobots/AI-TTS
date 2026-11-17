// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the `status` view of a daemon that does not play audio yet.
//!
//! Admission wording matches the Python `_speech_admission` for playback work.
//! With no playback controller, nothing is current, the listener's input is
//! unknown, and the playback state comes from the persisted hold and the counts.

use std::collections::BTreeMap;

use aitts_protocol::status::{Accepting, Status, StatusReply};
use aitts_protocol::value::{Nullable, Success};
use aitts_protocol::vocabulary::{PlaybackState, State, SubmissionDisposition};

use crate::runtime::EngineView;

/// The version `status` reports.
pub(crate) const VERSION: &str = env!("CARGO_PKG_VERSION");

const HELD_GUIDANCE: &str = "Speak freely: enqueue requested speech now, even while playback is paused. \
Speech is accepted and saved for playback when the hold is released. \
A microphone hold resumes automatically when input is idle if configured; \
a manual pause waits for the listener. Report queued, not played, until Played.";
const OPEN_GUIDANCE: &str = "Speak freely: speech is accepted into the playback queue.";

/// Build the status from what the store records.
pub(crate) fn status(
    engine: &EngineView,
    voice: String,
    held: bool,
    counts: BTreeMap<State, u64>,
) -> Status {
    let playback_state = if held {
        PlaybackState::Paused
    } else if counts
        .get(&State::Synthesizing)
        .is_some_and(|rows| *rows > 0)
    {
        PlaybackState::Synthesizing
    } else {
        PlaybackState::Idle
    };
    Status {
        version: VERSION.to_owned(),
        state: Accepting::Value,
        accepting_speech: Success,
        playback_held: held,
        submission_disposition: if held {
            SubmissionDisposition::SpooledUntilResume
        } else {
            SubmissionDisposition::QueuedForPlayback
        },
        submission_guidance: if held { HELD_GUIDANCE } else { OPEN_GUIDANCE }.to_owned(),
        playback_state,
        input_active: Nullable::Null,
        interruption: Nullable::Null,
        current: Nullable::Null,
        counts,
        engine: engine.name.clone(),
        engine_preparing: Nullable::Null,
        voice,
    }
}

/// The `status` reply: the same fields with the success flag.
pub(crate) fn reply(status: Status) -> StatusReply {
    StatusReply {
        ok: Success,
        version: status.version,
        state: status.state,
        accepting_speech: status.accepting_speech,
        playback_held: status.playback_held,
        submission_disposition: status.submission_disposition,
        submission_guidance: status.submission_guidance,
        playback_state: status.playback_state,
        input_active: status.input_active,
        interruption: status.interruption,
        current: status.current,
        counts: status.counts,
        engine: status.engine,
        engine_preparing: status.engine_preparing,
        voice: status.voice,
    }
}
