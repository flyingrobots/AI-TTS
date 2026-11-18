// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the `submit` and `requeue` operations, as Python
//! `_op_submit`, `_op_requeue` and `_replay`.
//!
//! It validates and resolves a submission on the API thread, then stores and
//! admits it through the conductor mailbox. Not covered yet: per-language voice
//! pools for agent sources, engine speed restrictions, clip evidence, events,
//! and reuse of a replayed item's cached audio.

use std::fs::File;
use std::io::Read;

use aitts_domain::segmentation::{self, ContentFormat as DomainFormat};
use aitts_domain::settings::{Speed, Value};
use aitts_domain::voices::{self, Claim, VoiceRequest};
use aitts_protocol::control_reply::Requeued;
use aitts_protocol::error_reply::ErrorCode;
use aitts_protocol::query_reply::Submitted;
use aitts_protocol::reply::Reply;
use aitts_protocol::value::{Nullable, Presence, Success};
use aitts_protocol::vocabulary::{
    ContentFormat, Priority, Sensitivity, State as WireState, SubmissionDisposition,
};
use aitts_store::Store;
use aitts_store::queue::NewUtterance;

use crate::api::Refusal;
use crate::conductor::durable::DurableError;
use crate::conductor::mailbox::{self, Mailbox};
use crate::connection::Shared;
use crate::projection::number;
use crate::runtime::EngineView;
use crate::runtime::publish;
use crate::settings_view::speaking_voice;
use aitts_protocol::catalog::Assignment;
use aitts_protocol::event::Event;

/// The submit fields this module reads, borrowed from the request.
pub(crate) struct Submission<'a> {
    pub(crate) text: &'a str,
    pub(crate) content_format: &'a Presence<ContentFormat>,
    pub(crate) voice: &'a Presence<Nullable<String>>,
    pub(crate) engine: &'a Presence<Nullable<String>>,
    pub(crate) speed: &'a Presence<Nullable<serde_json::Number>>,
    pub(crate) sensitivity: &'a Presence<Sensitivity>,
    pub(crate) priority: &'a Presence<Priority>,
    pub(crate) preempt: &'a Presence<bool>,
    pub(crate) playback: &'a Presence<bool>,
    pub(crate) source: &'a Presence<Nullable<String>>,
}

fn bad(message: impl Into<String>) -> Refusal {
    Refusal::new(ErrorCode::BadRequest, message)
}

fn present<T: Clone>(value: &Presence<T>) -> Option<T> {
    match value {
        Presence::Present(value) => Some(value.clone()),
        Presence::Absent => None,
    }
}

fn present_value<T: Clone>(value: &Presence<Nullable<T>>) -> Option<T> {
    match present(value)? {
        Nullable::Value(value) => Some(value),
        Nullable::Null => None,
    }
}

/// Accept `submission`, as Python `_op_submit`.
pub(crate) fn submit(
    mailbox: &Mailbox,
    store: &Store,
    engine: &EngineView,
    events: &Shared,
    submission: &Submission<'_>,
) -> Result<Reply, Refusal> {
    if submission.text.trim().is_empty() {
        return Err(bad("submit requires non-empty 'text'"));
    }
    let sensitivity = present(submission.sensitivity).unwrap_or(Sensitivity::Confidential);
    let mut priority = present(submission.priority).unwrap_or(Priority::Normal);
    if present(submission.preempt) == Some(true) {
        priority = Priority::Preempt;
    }
    let playback = present(submission.playback).unwrap_or(true);
    let requested = present_value(submission.engine).unwrap_or_else(|| engine.name.clone());
    if requested != engine.name {
        return Err(bad("selected model is not available in this daemon"));
    }
    if sensitivity != Sensitivity::Public && !engine.is_local {
        return Err(bad("private speech requires a local engine"));
    }
    let speed = speed(store, present_value(submission.speed))?;
    let format = present(submission.content_format).map(|format| match format {
        ContentFormat::PlainText => DomainFormat::PlainText,
        ContentFormat::Markdown => DomainFormat::Markdown,
    });
    let segments =
        segmentation::prepare(submission.text, format).map_err(|error| bad(error.to_string()))?;
    if segments.is_empty() {
        return Err(bad("submit text contains no speakable content"));
    }
    let source = present_value(submission.source);
    let requested_voice = present_value(submission.voice);
    let voice = voice(
        store,
        engine,
        events,
        source.as_deref(),
        requested_voice.as_deref(),
    )?;
    let composite =
        segments.len() != 1 || segments.first().map(String::as_str) != Some(submission.text);
    let mut new = NewUtterance::new(
        utterance_id()?,
        submission.text.to_owned(),
        voice.clone(),
        speed,
    );
    new.sensitivity = store_sensitivity(sensitivity);
    new.priority = store_priority(priority);
    new.at_head = priority != Priority::Normal;
    new.source = source;
    new.engine = Some(engine.name.clone());
    new.playback = playback;
    let segment_count = u64::try_from(segments.len()).map_err(|_| bad("too many segments"))?;
    new.segments = composite.then_some(segments);
    admit(mailbox, &new)?;
    let held = held(mailbox)?;
    let (disposition, guidance) = admission(playback, held);
    Ok(Reply::Submit(Submitted {
        ok: Success,
        accepted: Success,
        id: new.id,
        state: WireState::Queued,
        playback,
        voice,
        sensitivity,
        segment_count,
        composite,
        eligible_engines: if sensitivity == Sensitivity::Public || engine.is_local {
            vec![engine.name.clone()]
        } else {
            Vec::new()
        },
        accepting_speech: Success,
        playback_held: held,
        submission_disposition: disposition,
        submission_guidance: guidance.to_owned(),
    }))
}

/// Replay a finished utterance as a new one, as Python `_op_requeue`.
pub(crate) fn requeue(
    mailbox: &Mailbox,
    store: &Store,
    id: &str,
    priority: &Presence<Priority>,
) -> Result<Reply, Refusal> {
    let priority = present(priority).unwrap_or(Priority::Normal);
    let target = store
        .queue()
        .get(id)?
        .ok_or_else(|| Refusal::new(ErrorCode::NotFound, format!("no utterance {id}")))?;
    if !target.state.is_terminal() {
        return Err(Refusal::new(
            ErrorCode::IllegalState,
            "only a history item can be re-queued",
        ));
    }
    let segments: Vec<String> = store
        .queue()
        .segments(id)?
        .into_iter()
        .map(|segment| segment.text)
        .collect();
    let mut new = NewUtterance::new(utterance_id()?, target.text, target.voice, target.speed);
    new.sensitivity = target.sensitivity;
    new.priority = store_priority(priority);
    new.at_head = priority != Priority::Normal;
    new.source = target.source;
    new.replay_of = Some(target.id);
    new.engine = target.engine;
    let segment_count =
        u64::try_from(segments.len().max(1)).map_err(|_| bad("too many segments"))?;
    let composite = !segments.is_empty();
    new.segments = composite.then_some(segments);
    admit(mailbox, &new)?;
    Ok(Reply::Requeue(Requeued {
        ok: Success,
        id: new.id,
        state: WireState::Queued,
        priority,
        composite,
        segment_count,
    }))
}

fn admit(mailbox: &Mailbox, new: &NewUtterance) -> Result<(), Refusal> {
    match mailbox.request(mailbox::Request::Submit(new.clone())) {
        Ok(mailbox::Reply::Applied(Ok(_))) => Ok(()),
        Ok(mailbox::Reply::Applied(Err(DurableError::Refused(refused)))) => {
            Err(bad(refused.to_string()))
        }
        _ => Err(Refusal::new(
            ErrorCode::Internal,
            "internal error; see daemon log",
        )),
    }
}

fn held(mailbox: &Mailbox) -> Result<bool, Refusal> {
    match mailbox.request(mailbox::Request::Transport) {
        Ok(mailbox::Reply::Transport { held, .. }) => Ok(held),
        _ => Err(Refusal::new(
            ErrorCode::Internal,
            "internal error; see daemon log",
        )),
    }
}

/// An explicit speed in range, or the saved speaking speed, as `_submission_speed`.
fn speed(store: &Store, requested: Option<serde_json::Number>) -> Result<f64, Refusal> {
    let message = "speed must be a number from 0.5 to 2";
    match requested {
        Some(number) => {
            let value = number.as_f64().ok_or_else(|| bad(message))?;
            Speed::parse(Value::Number(value))
                .map(Speed::multiplier)
                .map_err(|_| bad(message))
        }
        None => Ok(store
            .settings()
            .get("speed", "1.0")?
            .trim()
            .parse()
            .unwrap_or(1.0)),
    }
}

/// Resolve the speaking voice and record a new client claim, as `VoiceRegistry.resolve`.
fn voice(
    store: &Store,
    engine: &EngineView,
    events: &Shared,
    source: Option<&str>,
    requested: Option<&str>,
) -> Result<String, Refusal> {
    let catalog: Vec<&str> = engine.voices.iter().map(String::as_str).collect();
    if let Some(requested) = requested.filter(|voice| !catalog.contains(voice)) {
        return Err(bad(format!("unknown voice '{requested}'")));
    }
    let assignment = match source {
        Some(source) => store
            .voices()
            .get(source)?
            .filter(|held| catalog.contains(&held.voice.as_str())),
        None => None,
    };
    let claimed = store.voices().claimed()?;
    let taken: Vec<&str> = claimed
        .iter()
        .map(String::as_str)
        .filter(|voice| assignment.as_ref().is_none_or(|held| held.voice != *voice))
        .collect();
    let default_voice = speaking_voice(store, engine)?;
    let decision = voices::decide(VoiceRequest {
        source,
        requested,
        default_voice: &default_voice,
        catalog: &catalog,
        pinned: assignment
            .as_ref()
            .filter(|held| held.pinned)
            .map(|held| held.voice.as_str()),
        claimed: assignment.as_ref().map(|held| held.voice.as_str()),
        taken: &taken,
    })
    .map_err(|_| bad("this engine has no voices"))?;
    let voice = decision.voice.to_owned();
    if let (Claim::Acquire, Some(source)) = (decision.claim, source) {
        let claimed = store.voices().claim(source, &voice)?;
        publish(
            events,
            &Event::VoiceAssigned {
                assignment: Assignment {
                    source: claimed.source,
                    voice: claimed.voice,
                    pinned: claimed.pinned,
                    assigned_at: number(claimed.assigned_at),
                },
            },
        );
    }
    Ok(voice)
}

/// Tell callers that a playback hold is not backpressure, as `_speech_admission`.
const fn admission(playback: bool, held: bool) -> (SubmissionDisposition, &'static str) {
    match (playback, held) {
        (false, _) => (
            SubmissionDisposition::SynthesisOnly,
            "Audio is being synthesized for the requesting client. Host speakers will not play it; host playback holds do not delay synthesis. Query get for segment readiness and cancel when the client is finished.",
        ),
        (true, true) => (
            SubmissionDisposition::SpooledUntilResume,
            "Speak freely: enqueue requested speech now, even while playback is paused. Speech is accepted and saved for playback when the hold is released. A microphone hold resumes automatically when input is idle if configured; a manual pause waits for the listener. Report queued, not played, until Played.",
        ),
        (true, false) => (
            SubmissionDisposition::QueuedForPlayback,
            "Speak freely: speech is accepted into the playback queue.",
        ),
    }
}

/// A new `utt_` identifier with 128 random bits, as Python `uuid4().hex`.
fn utterance_id() -> Result<String, Refusal> {
    let mut bytes = [0_u8; 16];
    File::open("/dev/urandom")
        .and_then(|mut random| random.read_exact(&mut bytes))
        .map_err(|_| Refusal::new(ErrorCode::Internal, "internal error; see daemon log"))?;
    let mut id = String::from("utt_");
    for byte in bytes {
        use std::fmt::Write as _;
        // Writing to a String cannot fail.
        let _infallible = write!(id, "{byte:02x}");
    }
    Ok(id)
}

const fn store_sensitivity(sensitivity: Sensitivity) -> aitts_store::Sensitivity {
    match sensitivity {
        Sensitivity::Public => aitts_store::Sensitivity::Public,
        Sensitivity::Internal => aitts_store::Sensitivity::Internal,
        Sensitivity::Confidential => aitts_store::Sensitivity::Confidential,
    }
}

const fn store_priority(priority: Priority) -> aitts_store::Priority {
    match priority {
        Priority::Normal => aitts_store::Priority::Normal,
        Priority::Urgent => aitts_store::Priority::Urgent,
        Priority::Preempt => aitts_store::Priority::Preempt,
    }
}
