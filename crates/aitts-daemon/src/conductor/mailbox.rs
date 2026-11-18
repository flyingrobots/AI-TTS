// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the conductor's bounded message channel.
//!
//! Every change reaches the one conductor owner as a [`Request`] through a bounded
//! channel, and the owner answers each request in arrival order. Callers hold
//! cloneable [`Mailbox`] handles; the owner drives an [`Inbox`] one request at a
//! time with [`Inbox::step`], or until shutdown with [`Inbox::serve`].
//!
//! Backpressure: [`Mailbox::try_request`] refuses with [`SendError::Full`] when the
//! channel is full, and [`Mailbox::request`] waits for space. Shutdown: requests
//! that arrived before [`Request::Shutdown`] are answered; later ones are dropped
//! unanswered, so their callers see [`SendError::Closed`], and change nothing.

use std::sync::mpsc::{Receiver, SyncSender, TrySendError, sync_channel};

use aitts_domain::utterance::State;
use aitts_store::queue::NewUtterance;

use super::durable::{Durable, DurableError, Ledger};
use super::{Clip, Command, Outcome, Transfer};

/// One request to the conductor owner.
#[derive(Clone, Debug, PartialEq)]
pub enum Request {
    /// Apply a command.
    Apply(Command),
    /// Store a new utterance and admit it; answered with [`Reply::Applied`].
    Submit(NewUtterance),
    /// Hand the next clip to synthesis.
    NextSynthesis,
    /// Decide the next device change.
    PlanPlayback,
    /// Read the clips in queue order.
    Clips,
    /// Read the hold and the clip on the device.
    Transport,
    /// Stop after answering every earlier request.
    Shutdown,
}

/// The owner's answer to one request.
#[derive(Debug)]
pub enum Reply {
    /// The result of [`Request::Apply`].
    Applied(Result<Outcome, DurableError>),
    /// The result of [`Request::NextSynthesis`].
    Synthesis(Result<Option<String>, DurableError>),
    /// The result of [`Request::PlanPlayback`].
    Planned(Result<Option<Transfer>, DurableError>),
    /// The answer to [`Request::Clips`].
    Clips(Vec<Clip>),
    /// The answer to [`Request::Transport`].
    Transport {
        /// Whether the playback hold is taken.
        held: bool,
        /// The clip on the device and its state.
        current: Option<(String, State)>,
    },
    /// The owner accepted [`Request::Shutdown`].
    Stopping,
}

/// Why a request was not delivered or not answered.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SendError {
    /// The channel is full; nothing was sent.
    Full,
    /// The owner has stopped; the request had no effect.
    Closed,
}

struct Envelope {
    request: Request,
    reply: SyncSender<Reply>,
}

/// A caller's handle. Cloning shares the same channel.
#[derive(Clone, Debug)]
pub struct Mailbox {
    sender: SyncSender<Envelope>,
}

impl std::fmt::Debug for Envelope {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Envelope")
            .field("request", &self.request)
            .finish_non_exhaustive()
    }
}

/// An answer that may not have arrived yet.
#[derive(Debug)]
pub struct Pending {
    reply: Receiver<Reply>,
}

impl Pending {
    /// Wait for the answer.
    ///
    /// # Errors
    /// Returns [`SendError::Closed`] when the owner stopped without answering.
    pub fn wait(self) -> Result<Reply, SendError> {
        self.reply.recv().map_err(|_| SendError::Closed)
    }
}

/// The owner's end of the channel.
#[derive(Debug)]
pub struct Inbox {
    receiver: Receiver<Envelope>,
}

/// What one [`Inbox::step`] did.
#[derive(Clone, Debug, PartialEq)]
pub enum Served {
    /// The request was answered.
    Answered(Request),
    /// Shutdown was requested, or every [`Mailbox`] was dropped.
    Stopped,
}

/// A channel holding at most `capacity` waiting requests.
pub fn channel(capacity: usize) -> (Mailbox, Inbox) {
    let (sender, receiver) = sync_channel(capacity);
    (Mailbox { sender }, Inbox { receiver })
}

impl Mailbox {
    /// Send without waiting for space.
    ///
    /// # Errors
    /// Returns [`SendError::Full`] or [`SendError::Closed`]; nothing was sent.
    pub fn try_request(&self, request: Request) -> Result<Pending, SendError> {
        let (reply, answer) = sync_channel(1);
        match self.sender.try_send(Envelope { request, reply }) {
            Ok(()) => Ok(Pending { reply: answer }),
            Err(TrySendError::Full(_)) => Err(SendError::Full),
            Err(TrySendError::Disconnected(_)) => Err(SendError::Closed),
        }
    }

    /// Send, waiting for space, then wait for the answer.
    ///
    /// # Errors
    /// Returns [`SendError::Closed`] when the owner stopped first.
    pub fn request(&self, request: Request) -> Result<Reply, SendError> {
        let (reply, answer) = sync_channel(1);
        self.sender
            .send(Envelope { request, reply })
            .map_err(|_| SendError::Closed)?;
        Pending { reply: answer }.wait()
    }
}

impl Inbox {
    /// Wait for one request and answer it.
    pub fn step<L: Ledger>(&self, durable: &mut Durable<L>) -> Served {
        let Ok(Envelope { request, reply }) = self.receiver.recv() else {
            return Served::Stopped;
        };
        let answer = match request.clone() {
            Request::Apply(command) => Reply::Applied(durable.apply(command)),
            Request::Submit(new) => Reply::Applied(durable.submit(&new)),
            Request::NextSynthesis => Reply::Synthesis(durable.next_synthesis()),
            Request::PlanPlayback => Reply::Planned(durable.plan_playback()),
            Request::Clips => Reply::Clips(durable.conductor().clips()),
            Request::Transport => {
                let conductor = durable.conductor();
                let current = conductor.current().and_then(|id| {
                    let clips = conductor.clips().into_iter();
                    clips
                        .filter(|clip| clip.id == id)
                        .map(|clip| (clip.id, clip.state))
                        .next()
                });
                Reply::Transport {
                    held: conductor.held(),
                    current,
                }
            }
            Request::Shutdown => {
                // A caller that stopped waiting does not stop the owner.
                let _unheard = reply.send(Reply::Stopping);
                return Served::Stopped;
            }
        };
        let _unheard = reply.send(answer);
        Served::Answered(request)
    }

    /// Answer requests until shutdown, dropping any that arrive after it.
    pub fn serve<L: Ledger>(self, durable: &mut Durable<L>) {
        while let Served::Answered(_) = self.step(durable) {}
        // Dropping `self` here drops every later request unanswered.
    }
}
