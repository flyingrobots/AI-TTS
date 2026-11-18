// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the operations that only read state.
//!
//! One API thread owns the store and answers requests in arrival order, as the
//! Python daemon's single event loop does. Operations that change state are
//! refused with `bad_request` until later issues port them.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::mpsc::{Receiver, SyncSender};
use std::time::Instant;

use aitts_protocol::catalog::{Assignment, Engine};
use aitts_protocol::control_reply::{Settings, Voices};
use aitts_protocol::error_reply::{DaemonError, ErrorCode, ErrorReply, Failure};
use aitts_protocol::metrics::{Cache, MetricsReply, QueueDepth};
use aitts_protocol::query_reply::{Item, Items};
use aitts_protocol::reply::Reply;
use aitts_protocol::request::{HistoryLimit, Request};
use aitts_protocol::snapshot::{Runtime, Snapshot};
use aitts_protocol::utterance::Utterance as WireUtterance;
use aitts_protocol::value::{Nullable, Presence, Success};
use aitts_protocol::vocabulary::{Queue, State};
use aitts_store::{Store, Utterance};

use crate::conductor::mailbox::Mailbox;
use crate::connection::Shared;
use crate::projection::{self, View, count, number};
use crate::runtime::EngineView;
use crate::{cache_usage, settings_view, status};
use crate::{control, submission};

/// One request and where to send its reply.
pub(crate) struct Job {
    pub(crate) request: Request,
    pub(crate) answer: SyncSender<Reply>,
}

/// A wire-visible refusal.
pub(crate) struct Refusal {
    code: ErrorCode,
    message: String,
}

impl Refusal {
    pub(crate) fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    pub(crate) fn into_reply(self) -> Reply {
        Reply::Error(ErrorReply {
            ok: Failure,
            error: DaemonError {
                r#type: self.code,
                message: self.message,
            },
        })
    }
}

impl From<aitts_store::Error> for Refusal {
    fn from(_: aitts_store::Error) -> Self {
        Self::new(ErrorCode::Internal, "internal error; see daemon log")
    }
}

/// The store and the observations a read operation reports.
pub(crate) struct ReadApi {
    pub(crate) store: Store,
    pub(crate) engine: EngineView,
    pub(crate) cache_dir: PathBuf,
    pub(crate) started: Instant,
    /// The conductor owner; every queue and transport change goes through it.
    pub(crate) conductor: Mailbox,
    /// Wakes the synthesis driver after a request, when one runs.
    pub(crate) wake: Option<SyncSender<()>>,
    /// Subscribers, for events this thread originates (voice claims).
    pub(crate) shared: Arc<Shared>,
}

/// Answer jobs until every sender is gone, then close the store.
pub(crate) fn serve(api: ReadApi, jobs: &Receiver<Job>) {
    while let Ok(job) = jobs.recv() {
        let reply = api.answer(&job.request);
        let _client_gone = job.answer.send(reply);
    }
    let _closed = api.store.close();
}

impl ReadApi {
    fn answer(&self, request: &Request) -> Reply {
        let reply = self.dispatch(request).unwrap_or_else(Refusal::into_reply);
        if let Some(wake) = &self.wake {
            // A full signal already wakes the driver; it re-reads all state.
            let _pending = wake.try_send(());
        }
        reply
    }

    fn dispatch(&self, request: &Request) -> Result<Reply, Refusal> {
        if let Some(answer) = control::answer(&self.conductor, &self.store, request) {
            return answer;
        }
        Ok(match request {
            Request::Submit {
                text,
                content_format,
                voice,
                engine,
                speed,
                sensitivity,
                priority,
                preempt,
                playback,
                source,
                origin: _,
            } => {
                let submission = submission::Submission {
                    text,
                    content_format,
                    voice,
                    engine,
                    speed,
                    sensitivity,
                    priority,
                    preempt,
                    playback,
                    source,
                };
                submission::submit(
                    &self.conductor,
                    &self.store,
                    &self.engine,
                    &self.shared,
                    &submission,
                )?
            }
            Request::Requeue { id, priority } => {
                submission::requeue(&self.conductor, &self.store, id, priority)?
            }
            Request::Status {} => Reply::Status(Box::new(status::reply(self.status()?))),
            Request::Get { id } => Reply::Get(self.get(id)?),
            Request::List { queue } => Reply::List(Items {
                ok: Success,
                items: self.project(&self.queue(*queue)?, View::Queue)?,
            }),
            Request::History { limit, before } => Reply::History(Items {
                ok: Success,
                items: self.history(limit, before, 100)?,
            }),
            Request::Voices {} => Reply::Voices(Voices {
                ok: Success,
                voices: self.engine.voices.clone(),
            }),
            Request::Settings { set } => Reply::Settings(self.settings(set)?),
            Request::Metrics {} => Reply::Metrics(self.metrics()?),
            Request::Snapshot { limit } => Reply::Snapshot(Box::new(self.snapshot(limit)?)),
            other => {
                return Err(Refusal::new(
                    ErrorCode::BadRequest,
                    format!(
                        "operation '{}' is not available in the Rust daemon yet",
                        other.operation().as_str()
                    ),
                ));
            }
        })
    }

    pub(crate) fn status(&self) -> Result<aitts_protocol::status::Status, Refusal> {
        Ok(status::status(
            &self.engine,
            settings_view::speaking_voice(&self.store, &self.engine)?,
            self.store.settings().get("playback_held", "false")? == "true",
            self.counts()?,
        ))
    }

    fn counts(&self) -> Result<BTreeMap<State, u64>, Refusal> {
        Ok(self
            .store
            .counts()?
            .into_iter()
            .map(|(stored, rows)| (projection::state(stored), rows))
            .collect())
    }

    fn get(&self, id: &str) -> Result<Item, Refusal> {
        let found = self
            .store
            .queue()
            .get(id)?
            .ok_or_else(|| Refusal::new(ErrorCode::NotFound, format!("no utterance '{id}'")))?;
        let view = if found.state.is_terminal() {
            View::History
        } else {
            View::Queue
        };
        let segments = self.store.queue().segments(&found.id)?;
        Ok(Item {
            ok: Success,
            item: projection::utterance(&found, &segments, view),
        })
    }

    fn queue(&self, queue: Queue) -> Result<Vec<Utterance>, Refusal> {
        Ok(match queue {
            Queue::Input => self.store.queue().input()?,
            Queue::Playback => self.store.queue().playback()?,
        })
    }

    fn history(
        &self,
        limit: &Presence<HistoryLimit>,
        before: &Presence<Nullable<String>>,
        default: u32,
    ) -> Result<Vec<WireUtterance>, Refusal> {
        let limit = match limit {
            Presence::Absent => default,
            Presence::Present(HistoryLimit::LegacyTrue(_)) => 1,
            Presence::Present(HistoryLimit::Count(0)) => {
                return Err(Refusal::new(
                    ErrorCode::BadRequest,
                    "'limit' must be a positive integer",
                ));
            }
            Presence::Present(HistoryLimit::Count(limit)) => {
                u32::try_from(*limit).unwrap_or(u32::MAX)
            }
        };
        let before = match before {
            Presence::Present(Nullable::Value(id)) => Some(id.as_str()),
            Presence::Absent | Presence::Present(Nullable::Null) => None,
        };
        let rows = self.store.history().list(limit, before)?;
        self.project(&rows, View::History)
    }

    fn project(&self, rows: &[Utterance], view: View) -> Result<Vec<WireUtterance>, Refusal> {
        rows.iter()
            .map(|row| {
                let segments = self.store.queue().segments(&row.id)?;
                Ok(projection::utterance(row, &segments, view))
            })
            .collect()
    }

    fn settings(
        &self,
        set: &Presence<Nullable<aitts_protocol::settings::SettingsUpdate>>,
    ) -> Result<Settings, Refusal> {
        if let Presence::Present(Nullable::Value(_)) = set {
            return Err(Refusal::new(
                ErrorCode::BadRequest,
                "settings updates are not available in the Rust daemon yet",
            ));
        }
        Ok(Settings {
            ok: Success,
            settings: settings_view::snapshot(&self.store, &self.engine)?,
        })
    }

    fn metrics(&self) -> Result<MetricsReply, Refusal> {
        let limit = self.store.settings().get("cache_max_bytes", "")?;
        Ok(MetricsReply {
            ok: Success,
            counts: self.counts()?,
            queue_depth: QueueDepth {
                input: count(self.store.queue().input()?.len()),
                playback: count(self.store.queue().playback()?.len()),
            },
            cache: Cache {
                bytes: cache_usage::cached_bytes(&self.cache_dir),
                max_bytes: settings_view::cache_limit(&limit),
            },
            synthesis_wait_ms: Nullable::Null,
            synthesis_duration_ms: Nullable::Null,
            playback_wait_ms: Nullable::Null,
            playback_failures: 0,
        })
    }

    fn snapshot(&self, limit: &Presence<HistoryLimit>) -> Result<Snapshot, Refusal> {
        let playback = self.store.queue().playback()?;
        let input = self.store.queue().input()?;
        let mut plan: Vec<Utterance> = playback.iter().chain(&input).cloned().collect();
        plan.sort_by(|a, b| a.order_key.total_cmp(&b.order_key));
        Ok(Snapshot {
            ok: Success,
            status: self.status()?,
            runtime: Runtime {
                pid: u64::from(std::process::id()),
                uptime_seconds: number(self.started.elapsed().as_secs_f64()),
                model_state: self.engine.state,
                active_synthesis: 0,
            },
            playback: self.project(&playback, View::Queue)?,
            input: self.project(&input, View::Queue)?,
            plan: self.project(&plan, View::Queue)?,
            history: self.history(limit, &Presence::Absent, 50)?,
            voices: self.engine.voices.clone(),
            engines: vec![Engine {
                name: self.engine.name.clone(),
                is_local: self.engine.is_local,
                voices: self.engine.voices.clone(),
                state: self.engine.state,
                selected: true,
            }],
            models: Vec::new(),
            voice_assignments: self
                .store
                .voices()
                .list()?
                .into_iter()
                .map(|held| Assignment {
                    source: held.source,
                    voice: held.voice,
                    pinned: held.pinned,
                    assigned_at: number(held.assigned_at),
                })
                .collect(),
            settings: settings_view::snapshot(&self.store, &self.engine)?,
        })
    }
}
