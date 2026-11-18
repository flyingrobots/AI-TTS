// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small for single-thread tests; the two thread tests are medium.
//! The conductor's bounded channel: order, backpressure, shutdown, interleavings.
//! Oracle: the contract in `conductor::mailbox` module docs; for concurrent
//! clients, a sequential replay of the recorded schedule (linearizability).
//! Interleavings are forced, never raced: the owner is driven one request at a
//! time with `Inbox::step` on the test thread, and the queue is filled before
//! the owner runs, so each test has exactly one possible schedule, except
//! `concurrent_clients_*`, which records its schedule and checks it.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use std::thread;

use aitts_daemon::conductor::durable::{Change, Durable, Ledger, LedgerError};
use aitts_daemon::conductor::mailbox::{Reply, Request, SendError, Served, channel};
use aitts_daemon::conductor::{Clip, Command, Outcome};
use aitts_domain::plan::{Playback, Priority};

/// A ledger that always persists, so these tests observe only the channel.
struct Accepting;
impl Ledger for Accepting {
    fn record(&mut self, _changes: &[Change]) -> Result<(), LedgerError> {
        Ok(())
    }
    fn recover(&mut self) -> Result<Vec<Clip>, LedgerError> {
        Ok(Vec::new())
    }
}

fn durable() -> Durable<Accepting> {
    Durable::recover(Accepting).unwrap()
}

fn submit(id: &str) -> Request {
    Request::Apply(Command::Submit {
        id: id.to_owned(),
        priority: Priority::Normal,
        playback: Playback::Play,
    })
}

fn ids(durable: &Durable<Accepting>) -> Vec<String> {
    durable
        .conductor()
        .clips()
        .into_iter()
        .map(|clip| clip.id)
        .collect()
}

fn applied(reply: &Reply) -> bool {
    matches!(reply, Reply::Applied(Ok(Outcome::Applied)))
}

#[test]
fn requests_are_answered_in_arrival_order() {
    let (mailbox, inbox) = channel(4);
    let first = mailbox.try_request(submit("a")).unwrap();
    let second = mailbox.try_request(submit("b")).unwrap();
    let clips = mailbox.try_request(Request::Clips).unwrap();
    mailbox.try_request(Request::Shutdown).unwrap();
    inbox.serve(&mut durable());
    assert!(applied(&first.wait().unwrap()), "first submit not applied");
    assert!(
        applied(&second.wait().unwrap()),
        "second submit not applied"
    );
    let Reply::Clips(clips) = clips.wait().unwrap() else {
        panic!("clips request not answered with clips")
    };
    let order: Vec<String> = clips.into_iter().map(|clip| clip.id).collect();
    assert_eq!(order, ["a", "b"]);
}

#[test]
fn a_full_channel_refuses_without_sending() {
    let (mailbox, inbox) = channel(1);
    let mut owner = durable();
    mailbox.try_request(submit("a")).unwrap();
    assert_eq!(
        mailbox.try_request(submit("b")).unwrap_err(),
        SendError::Full
    );
    assert_eq!(inbox.step(&mut owner), Served::Answered(submit("a")));
    mailbox.try_request(Request::Shutdown).unwrap();
    assert_eq!(inbox.step(&mut owner), Served::Stopped);
    assert_eq!(ids(&owner), ["a"], "a refused request changed the queue");
}

#[test]
fn shutdown_answers_earlier_requests_and_drops_later_ones() {
    let (mailbox, inbox) = channel(4);
    let mut owner = durable();
    let before = mailbox.try_request(submit("before")).unwrap();
    let stop = mailbox.try_request(Request::Shutdown).unwrap();
    let after = mailbox.try_request(submit("after")).unwrap();
    inbox.serve(&mut owner);
    assert!(
        applied(&before.wait().unwrap()),
        "request before shutdown not applied"
    );
    assert!(
        matches!(stop.wait().unwrap(), Reply::Stopping),
        "shutdown not acknowledged"
    );
    assert_eq!(after.wait().unwrap_err(), SendError::Closed);
    assert_eq!(ids(&owner), ["before"]);
}

#[test]
fn a_request_after_the_owner_stops_is_closed() {
    let (mailbox, inbox) = channel(1);
    drop(inbox);
    assert_eq!(
        mailbox.try_request(submit("a")).unwrap_err(),
        SendError::Closed
    );
    assert_eq!(mailbox.request(submit("a")).unwrap_err(), SendError::Closed);
}

#[test]
fn a_blocked_sender_proceeds_when_the_owner_takes_a_message() {
    let (mailbox, inbox) = channel(1);
    let mut owner = durable();
    mailbox.try_request(submit("queued")).unwrap();
    thread::scope(|scope| {
        // The channel is full, so this send can only enter after "queued" leaves.
        let blocked = scope.spawn(|| mailbox.request(submit("blocked")));
        assert_eq!(inbox.step(&mut owner), Served::Answered(submit("queued")));
        assert_eq!(inbox.step(&mut owner), Served::Answered(submit("blocked")));
        assert!(
            applied(&blocked.join().unwrap().unwrap()),
            "blocked request not applied"
        );
    });
    assert_eq!(ids(&owner), ["queued", "blocked"]);
}

#[test]
fn concurrent_clients_give_a_history_equal_to_its_sequential_replay() {
    let (mailbox, inbox) = channel(1);
    let mut owner = durable();
    let mut schedule = Vec::new();
    thread::scope(|scope| {
        for client in ["x", "y"] {
            let mailbox = mailbox.clone();
            scope.spawn(move || {
                for index in 0..5 {
                    assert!(applied(
                        &mailbox
                            .request(submit(&format!("{client}{index}")))
                            .unwrap()
                    ));
                }
            });
        }
        for _ in 0..10 {
            let Served::Answered(request) = inbox.step(&mut owner) else {
                panic!("owner stopped early")
            };
            schedule.push(request);
        }
    });
    let mut replay = durable();
    for request in &schedule {
        let Request::Apply(command) = request.clone() else {
            panic!("unexpected {request:?}")
        };
        replay.apply(command).unwrap();
    }
    assert_eq!(
        ids(&owner),
        ids(&replay),
        "history differs from its replay; schedule {schedule:?}"
    );
    for client in ["x", "y"] {
        let own: Vec<String> = ids(&owner)
            .into_iter()
            .filter(|id| id.starts_with(client))
            .collect();
        let expected: Vec<String> = (0..5).map(|index| format!("{client}{index}")).collect();
        assert_eq!(
            own, expected,
            "client {client} reordered; schedule {schedule:?}"
        );
    }
}
