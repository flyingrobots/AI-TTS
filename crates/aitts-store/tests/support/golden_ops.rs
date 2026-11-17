// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! The `golden` operations of `tests/fixtures/generate.py`, performed through the Rust store.
//!
//! Each call reads the clock as often as its Python counterpart, so equal clocks give equal rows.

use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{Priority, Result, Sensitivity, State, Store};

fn new(id: &str, text: &str, voice: &str, speed: f64) -> NewUtterance {
    NewUtterance::new(id.to_owned(), text.to_owned(), voice.to_owned(), speed)
}

/// Write the golden rows; ids follow the generator's `utt_0001` sequence.
///
/// # Errors
/// Returns the first store failure.
pub(crate) fn write(store: &Store) -> Result<()> {
    let queue = store.queue();
    let mut played = new("utt_0001", "played text", "af_heart", 1.25);
    played.source = Some("agent-a".to_owned());
    played.sensitivity = Sensitivity::Public;
    played.engine = Some("kokoro".to_owned());
    queue.submit(&played)?;
    queue.transition("utt_0001", State::Synthesizing, &Fields::default())?;
    let audio = Fields {
        audio_path: Some("/cache/played.wav".to_owned()),
        duration_ms: Some(900),
        ..Fields::default()
    };
    queue.transition("utt_0001", State::Ready, &audio)?;
    queue.transition("utt_0001", State::Playing, &Fields::default())?;
    let done = Fields {
        played_ms: Some(900),
        ..Fields::default()
    };
    queue.transition("utt_0001", State::Played, &done)?;

    let mut failed = new("utt_0002", "failed text", "bm_daniel", 1.0);
    failed.priority = Priority::Urgent;
    failed.sensitivity = Sensitivity::Internal;
    queue.submit(&failed)?;
    queue.transition("utt_0002", State::Synthesizing, &Fields::default())?;
    let error = Fields {
        error: Some("engine exploded".to_owned()),
        ..Fields::default()
    };
    queue.transition("utt_0002", State::Failed, &error)?;

    let mut replay = new("utt_0003", "replay", "af_heart", 1.0);
    replay.replay_of = Some("utt_0001".to_owned());
    replay.playback = false;
    queue.submit(&replay)?;

    let mut doc = new("utt_0004", "doc", "bm_daniel", 1.0);
    doc.segments = Some(vec!["one".to_owned(), "two".to_owned()]);
    queue.submit(&doc)?;
    queue.transition("utt_0004", State::Synthesizing, &Fields::default())?;
    queue.transition_segment("utt_0004", 0, State::Synthesizing, &Fields::default())?;
    let segment_audio = Fields {
        audio_path: Some("/cache/seg0.wav".to_owned()),
        duration_ms: Some(300),
        ..Fields::default()
    };
    queue.transition_segment("utt_0004", 0, State::Ready, &segment_audio)?;
    queue.transition("utt_0004", State::Ready, &Fields::default())?;

    let mut head = new("utt_0005", "head", "v", 1.0);
    head.priority = Priority::Preempt;
    head.at_head = true;
    queue.submit(&head)?;

    let settings = store.settings();
    settings.set("speed", "1.5")?;
    settings.set("default_voice", "af_heart")?;
    let voices = store.voices();
    voices.pin("listener-pick", "bm_daniel")?;
    voices.claim("agent-a", "af_heart")?;
    Ok(())
}
