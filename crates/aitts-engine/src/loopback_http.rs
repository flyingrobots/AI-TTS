// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! This module owns speech through a separately managed OpenAI-compatible
//! server on loopback. Text never leaves the machine: the URL must name
//! `localhost` (pinned to 127.0.0.1, no DNS) or a literal loopback address.
//! There are no proxies and no redirects. HTTPS is not supported yet.

use std::io::{ErrorKind, Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::time::Duration;

use crate::engine::{Engine, EngineError, SpeechRequest};

const HEADER_LIMIT: usize = 64 * 1024;

/// One loopback speech server. Each request gives the whole WAV body to the sink once.
#[derive(Debug)]
pub struct LoopbackHttpEngine {
    address: SocketAddr,
    path: String,
    model: String,
    timeout: Duration,
    max_response_bytes: usize,
}

impl LoopbackHttpEngine {
    /// Validate `url` and keep the server `model` name.
    ///
    /// # Errors
    /// The URL is not plain HTTP on loopback, or a limit is zero.
    pub fn new(
        url: &str,
        model: &str,
        timeout: Duration,
        max_response_bytes: usize,
    ) -> Result<Self, EngineError> {
        if url.starts_with("https://") {
            return Err(EngineError::Refused(
                "HTTPS loopback servers are not supported yet",
            ));
        }
        let rest = url
            .strip_prefix("http://")
            .filter(|rest| !rest.contains(['@', '?', '#']))
            .ok_or(EngineError::Refused(
                "speech URL must be plain HTTP without credentials, query or fragment",
            ))?;
        let (authority, path) = rest.find('/').map_or((rest, ""), |at| rest.split_at(at));
        let address = loopback_address(authority)?;
        if model.trim().is_empty() || timeout.is_zero() || max_response_bytes == 0 {
            return Err(EngineError::Refused(
                "model, time limit and byte limit must be set",
            ));
        }
        let path = path.trim_end_matches('/');
        let path = if path.ends_with("/audio/speech") {
            path.to_owned()
        } else if path.ends_with("/v1") {
            format!("{path}/audio/speech")
        } else {
            format!("{path}/v1/audio/speech")
        };
        Ok(Self {
            address,
            path,
            model: model.to_owned(),
            timeout,
            max_response_bytes,
        })
    }

    pub fn address(&self) -> SocketAddr {
        self.address
    }

    fn post(&self, body: &[u8]) -> Result<Vec<u8>, EngineError> {
        let mut stream = TcpStream::connect_timeout(&self.address, self.timeout)?;
        stream.set_read_timeout(Some(self.timeout))?;
        stream.set_write_timeout(Some(self.timeout))?;
        // HTTP/1.0 with Connection: close: the body ends at EOF and is never chunked.
        let head = format!(
            "POST {} HTTP/1.0\r\nHost: {}\r\nContent-Type: application/json\r\nAccept: audio/wav\r\n\
             Content-Length: {}\r\nConnection: close\r\n\r\n",
            self.path,
            self.address,
            body.len()
        );
        stream.write_all(head.as_bytes())?;
        stream.write_all(body)?;
        let mut response = Vec::new();
        let limit = HEADER_LIMIT
            .saturating_add(self.max_response_bytes)
            .saturating_add(1);
        stream
            .take(u64::try_from(limit).unwrap_or(u64::MAX))
            .read_to_end(&mut response)?;
        self.body(response)
    }

    fn body(&self, mut response: Vec<u8>) -> Result<Vec<u8>, EngineError> {
        let end = response
            .windows(4)
            .position(|w| w == b"\r\n\r\n")
            .filter(|&end| end <= HEADER_LIMIT)
            .ok_or(EngineError::InvalidResponse(
                "HTTP header missing or too long",
            ))?;
        let body = response.split_off(end.saturating_add(4));
        let head = String::from_utf8(response)
            .map_err(|_| EngineError::InvalidResponse("HTTP header is not UTF-8"))?;
        let mut lines = head.split("\r\n");
        let status = lines.next().and_then(|l| l.split(' ').nth(1));
        if status != Some("200") {
            return Err(EngineError::Refused(
                "speech server did not return 200; redirects are not followed",
            ));
        }
        if body.len() > self.max_response_bytes || body.is_empty() {
            return Err(EngineError::InvalidResponse(
                "speech body is empty or over the byte limit",
            ));
        }
        let declared = lines
            .filter_map(|l| l.split_once(':'))
            .find(|(name, _)| name.trim().eq_ignore_ascii_case("content-length"))
            .map(|(_, value)| value.trim().parse::<usize>());
        match declared {
            Some(Ok(length)) if length != body.len() => Err(EngineError::InvalidResponse(
                "speech body differs from its declared length",
            )),
            Some(Err(_)) => Err(EngineError::InvalidResponse("invalid Content-Length")),
            _ => Ok(body),
        }
    }
}

fn loopback_address(authority: &str) -> Result<SocketAddr, EngineError> {
    let refused =
        EngineError::Refused("speech URL must name localhost or a literal loopback address");
    let (host, port) = match authority.rsplit_once(':') {
        Some((host, port)) if !port.contains(']') => (host, Some(port)),
        _ => (authority, None),
    };
    let port = match port {
        None => 80,
        Some(port) => port
            .parse::<u16>()
            .ok()
            .filter(|&p| p != 0)
            .ok_or(EngineError::Refused("invalid port"))?,
    };
    let host = host
        .strip_prefix('[')
        .and_then(|h| h.strip_suffix(']'))
        .unwrap_or(host);
    let ip = if host.eq_ignore_ascii_case("localhost") {
        IpAddr::V4(Ipv4Addr::LOCALHOST)
    } else {
        host.parse::<IpAddr>().map_err(|_| refused)?
    };
    if !ip.is_loopback() {
        return Err(EngineError::Refused(
            "speech server must be on loopback; remote text transmission is disabled",
        ));
    }
    Ok(SocketAddr::new(ip, port))
}

impl Engine for LoopbackHttpEngine {
    fn name(&self) -> &'static str {
        "openai-audio"
    }

    fn stream(
        &mut self,
        request: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        let body = serde_json::json!({
            "input": request.text, "voice": request.voice, "model": self.model,
            "speed": request.speed, "response_format": "wav",
        });
        let wav = self
            .post(body.to_string().as_bytes())
            .map_err(|error| match error {
                EngineError::Io(io)
                    if matches!(io.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) =>
                {
                    EngineError::Timeout
                }
                other => other,
            })?;
        sink(&wav);
        Ok(())
    }
}
