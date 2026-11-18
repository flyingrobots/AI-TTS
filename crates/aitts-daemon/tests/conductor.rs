// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (pure state, one thread, no I/O).
//! Conformance suite for the conductor's queue operations.
//! Oracles: `store.py` (`clear_pending`, `reorder_pending`), `daemon.py` (`_op_cancel`,
//! `_op_clear`) and `playback.py` (`_plan_preemption`, `_restore_preempted`,
//! `clear_preempted`, `_hold`) on main, read as the specification.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use aitts_daemon::conductor::{Command, Conductor, Outcome, Refusal, Transfer};
use aitts_domain::plan::{Playback, Priority};
use aitts_domain::utterance::State;

fn submit(conductor: &mut Conductor, id: &str, priority: Priority) {
    let command = Command::Submit {
        id: id.to_owned(),
        priority,
        playback: Playback::Play,
    };
    assert_eq!(
        conductor.apply(command),
        Ok(Outcome::Applied),
        "submit {id}"
    );
}

/// Submit, synthesize and ready one clip.
fn ready(conductor: &mut Conductor, id: &str, priority: Priority) {
    submit(conductor, id, priority);
    assert_eq!(
        conductor.next_synthesis().as_deref(),
        Some(id),
        "synthesis of {id}"
    );
    let ready = Command::AudioReady(id.to_owned());
    assert_eq!(
        conductor.apply(ready),
        Ok(Outcome::Applied),
        "audio for {id}"
    );
}

fn state(conductor: &Conductor, id: &str) -> State {
    conductor
        .clips()
        .into_iter()
        .find(|clip| clip.id == id)
        .expect(id)
        .state
}

fn order(conductor: &Conductor) -> Vec<String> {
    conductor.clips().into_iter().map(|clip| clip.id).collect()
}

#[expect(
    clippy::unnecessary_wraps,
    reason = "compared with the planner's Option"
)]
fn start(id: &str) -> Option<Transfer> {
    Some(Transfer::Start(id.to_owned()))
}

#[test]
fn submit_appends_normal_and_puts_urgent_ahead_of_unfinished_work() {
    let mut conductor = Conductor::new();
    submit(&mut conductor, "a", Priority::Normal);
    submit(&mut conductor, "b", Priority::Normal);
    submit(&mut conductor, "u", Priority::Urgent);
    assert_eq!(order(&conductor), ["u", "a", "b"]);
}

#[test]
fn submit_refuses_a_duplicate_identifier() {
    let mut conductor = Conductor::new();
    submit(&mut conductor, "a", Priority::Normal);
    let again = Command::Submit {
        id: "a".to_owned(),
        priority: Priority::Normal,
        playback: Playback::Play,
    };
    assert_eq!(
        conductor.apply(again),
        Err(Refusal::Duplicate("a".to_owned()))
    );
}

#[test]
fn cancel_refuses_the_speaker_on_the_device() {
    let mut conductor = Conductor::new();
    ready(&mut conductor, "a", Priority::Normal);
    assert_eq!(conductor.plan_playback(), start("a"));
    let refused = conductor.apply(Command::Cancel("a".to_owned()));
    let expected = Refusal::IllegalState {
        id: "a".to_owned(),
        state: State::Playing,
    };
    assert_eq!(refused, Err(expected));
}

#[test]
fn cancel_refuses_an_unknown_identifier() {
    let mut conductor = Conductor::new();
    let refused = conductor.apply(Command::Cancel("missing".to_owned()));
    assert_eq!(refused, Err(Refusal::NotFound("missing".to_owned())));
}

#[test]
fn audio_for_a_clip_cancelled_during_synthesis_is_discarded() {
    let mut conductor = Conductor::new();
    submit(&mut conductor, "a", Priority::Normal);
    assert_eq!(conductor.next_synthesis().as_deref(), Some("a"));
    assert_eq!(
        conductor.apply(Command::Cancel("a".to_owned())),
        Ok(Outcome::Applied)
    );
    assert_eq!(
        conductor.apply(Command::AudioReady("a".to_owned())),
        Ok(Outcome::Discarded)
    );
    assert_eq!(state(&conductor, "a"), State::Cancelled);
}

#[test]
fn one_failed_synthesis_does_not_stop_later_clips() {
    let mut conductor = Conductor::new();
    submit(&mut conductor, "bad", Priority::Normal);
    submit(&mut conductor, "good", Priority::Normal);
    assert_eq!(conductor.next_synthesis().as_deref(), Some("bad"));
    let failed = conductor.apply(Command::SynthesisFailed("bad".to_owned()));
    assert_eq!(failed, Ok(Outcome::Applied));
    assert_eq!(conductor.next_synthesis().as_deref(), Some("good"));
}

#[test]
fn reorder_assigns_the_permutation_after_the_current_speaker() {
    let mut conductor = Conductor::new();
    ready(&mut conductor, "now", Priority::Normal);
    assert_eq!(conductor.plan_playback(), start("now"));
    submit(&mut conductor, "a", Priority::Normal);
    submit(&mut conductor, "b", Priority::Normal);
    let ids = vec!["b".to_owned(), "a".to_owned()];
    assert_eq!(conductor.apply(Command::Reorder(ids)), Ok(Outcome::Applied));
    assert_eq!(order(&conductor), ["now", "b", "a"]);
}

#[test]
fn reorder_refuses_a_partial_permutation_and_keeps_order() {
    let mut conductor = Conductor::new();
    submit(&mut conductor, "a", Priority::Normal);
    submit(&mut conductor, "b", Priority::Normal);
    let refused = conductor.apply(Command::Reorder(vec!["b".to_owned()]));
    assert_eq!(refused, Err(Refusal::NotPermutation));
    assert_eq!(order(&conductor), ["a", "b"]);
}

#[test]
fn a_hold_taken_with_the_first_audio_keeps_the_device_idle() {
    let mut conductor = Conductor::new();
    submit(&mut conductor, "a", Priority::Normal);
    assert_eq!(conductor.next_synthesis().as_deref(), Some("a"));
    assert_eq!(conductor.apply(Command::Pause), Ok(Outcome::Applied));
    assert_eq!(
        conductor.apply(Command::AudioReady("a".to_owned())),
        Ok(Outcome::Applied)
    );
    assert_eq!(conductor.plan_playback(), None);
}

#[test]
fn pause_and_resume_move_the_current_speaker_between_paused_and_playing() {
    let mut conductor = Conductor::new();
    ready(&mut conductor, "a", Priority::Normal);
    assert_eq!(conductor.plan_playback(), start("a"));
    assert_eq!(conductor.apply(Command::Pause), Ok(Outcome::Applied));
    assert_eq!(state(&conductor, "a"), State::Paused);
    assert_eq!(conductor.apply(Command::Resume), Ok(Outcome::Applied));
    assert_eq!(state(&conductor, "a"), State::Playing);
}

#[test]
fn nested_preemption_restores_speakers_newest_first() {
    let mut conductor = Conductor::new();
    ready(&mut conductor, "base", Priority::Normal);
    assert_eq!(conductor.plan_playback(), start("base"));
    ready(&mut conductor, "alert1", Priority::Preempt);
    let first = Transfer::Preempt {
        suspended: Some("base".to_owned()),
        started: "alert1".to_owned(),
    };
    assert_eq!(conductor.plan_playback(), Some(first));
    ready(&mut conductor, "alert2", Priority::Preempt);
    let second = Transfer::Preempt {
        suspended: Some("alert1".to_owned()),
        started: "alert2".to_owned(),
    };
    assert_eq!(conductor.plan_playback(), Some(second));
    let finished = conductor.apply(Command::PlaybackFinished("alert2".to_owned()));
    assert_eq!(finished, Ok(Outcome::Applied));
    assert_eq!(
        conductor.plan_playback(),
        Some(Transfer::Restore("alert1".to_owned()))
    );
    let finished = conductor.apply(Command::PlaybackFinished("alert1".to_owned()));
    assert_eq!(finished, Ok(Outcome::Applied));
    assert_eq!(
        conductor.plan_playback(),
        Some(Transfer::Restore("base".to_owned()))
    );
}

#[test]
fn clearing_during_a_preemption_skips_suspended_speakers_and_keeps_the_alert() {
    let mut conductor = Conductor::new();
    ready(&mut conductor, "base", Priority::Normal);
    assert_eq!(conductor.plan_playback(), start("base"));
    submit(&mut conductor, "later", Priority::Normal);
    ready(&mut conductor, "alert", Priority::Preempt);
    let preempt = Transfer::Preempt {
        suspended: Some("base".to_owned()),
        started: "alert".to_owned(),
    };
    assert_eq!(conductor.plan_playback(), Some(preempt));
    assert_eq!(
        conductor.apply(Command::ClearQueue),
        Ok(Outcome::Cleared(2))
    );
    let states: Vec<State> = ["base", "later", "alert"]
        .map(|id| state(&conductor, id))
        .to_vec();
    assert_eq!(states, [State::Skipped, State::Cancelled, State::Playing]);
}
