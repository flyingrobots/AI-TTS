// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (an owned loopback socket and one thread). Oracle: the Python
//! `openai_compatible.py` adapter contract: loopback only, no redirects, a
//! byte limit, and a body that matches its declared length.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]
#![allow(clippy::indexing_slicing, reason = "read count bounds the slice")]

use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread;
use std::time::Duration;

use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::loopback_http::LoopbackHttpEngine;

const LIMIT: usize = 1024;

fn engine(url: &str) -> Result<LoopbackHttpEngine, EngineError> {
    LoopbackHttpEngine::new(url, "tts-1", Duration::from_secs(5), LIMIT)
}

/// Serve one canned `response` and return the request the engine sent.
fn serve(response: Vec<u8>) -> (String, thread::JoinHandle<Vec<u8>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/v1", listener.local_addr().unwrap());
    let server = thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        let mut request = Vec::new();
        let mut block = [0_u8; 4096];
        // The JSON body ends the request.
        while !request.ends_with(b"}") {
            let read = socket.read(&mut block).unwrap();
            assert!(read > 0, "request ended early");
            request.extend_from_slice(&block[..read]);
        }
        // The engine may close early on an oversized body.
        drop(socket.write_all(&response));
        request
    });
    (url, server)
}

fn speak(engine: &mut LoopbackHttpEngine) -> (Result<(), EngineError>, Vec<u8>) {
    let mut body = Vec::new();
    let request = SpeechRequest {
        text: "hi",
        voice: "alloy",
        speed: 1.0,
    };
    let result = engine.stream(&request, &mut |wav| body.extend_from_slice(wav));
    (result, body)
}

#[test]
fn remote_and_unsafe_urls_are_refused() {
    for url in [
        "http://192.168.1.2:8880",
        "http://example.com",
        "https://127.0.0.1",
        "http://user@127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1/?q=1",
        "ftp://127.0.0.1",
    ] {
        assert!(matches!(engine(url), Err(EngineError::Refused(_))), "{url}");
    }
    assert!(engine("http://localhost:8880").is_ok_and(|e| e.address().ip().is_loopback()));
    assert!(engine("http://[::1]:8880").is_ok());
}

#[test]
fn a_known_body_reaches_the_sink_from_the_speech_path() {
    let (url, server) = serve(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nRIFF".to_vec());
    let (result, body) = speak(&mut engine(&url).unwrap());
    assert!(result.is_ok(), "{result:?}");
    assert_eq!(body, b"RIFF");
    let request = String::from_utf8(server.join().unwrap()).unwrap();
    assert!(
        request.starts_with("POST /v1/audio/speech HTTP/1.0\r\n"),
        "{request}"
    );
    assert!(request.contains("\"model\":\"tts-1\""), "{request}");
}

#[test]
fn redirects_short_bodies_and_oversized_bodies_are_refused() {
    let oversized = [b"HTTP/1.1 200 OK\r\n\r\n".to_vec(), vec![0; LIMIT + 1]].concat();
    for response in [
        b"HTTP/1.1 302 Found\r\nLocation: http://example.com/\r\nContent-Length: 4\r\n\r\nRIFF"
            .to_vec(),
        b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nRIFF".to_vec(),
        oversized,
    ] {
        let (url, server) = serve(response);
        let (result, body) = speak(&mut engine(&url).unwrap());
        assert!(result.is_err());
        assert_eq!(body, Vec::<u8>::new());
        server.join().unwrap();
    }
}
