#![allow(dead_code)]
//! A tiny HTTP server standing in for the Rekamind backend, recording what it was sent.
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::thread;

#[derive(Debug, Clone)]
pub struct Req {
    pub method: String,
    pub path: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}
impl Req {
    pub fn header(&self, k: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(n, _)| n.eq_ignore_ascii_case(k))
            .map(|(_, v)| v.as_str())
    }
}

pub struct Mock {
    pub url: String,
    pub seen: Arc<Mutex<Vec<Req>>>,
}

fn read_request(s: &mut TcpStream) -> Option<Req> {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 4096];
    let head_end = loop {
        let n = s.read(&mut tmp).ok()?;
        if n == 0 {
            return None;
        }
        buf.extend_from_slice(&tmp[..n]);
        if let Some(p) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
            break p + 4;
        }
    };
    let head = String::from_utf8_lossy(&buf[..head_end]).into_owned();
    let mut lines = head.lines();
    let mut first = lines.next()?.split_whitespace();
    let (method, path) = (first.next()?.to_string(), first.next()?.to_string());
    let headers: Vec<(String, String)> = lines
        .filter_map(|l| l.split_once(':'))
        .map(|(k, v)| (k.trim().to_string(), v.trim().to_string()))
        .collect();
    let len: usize = headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
        .and_then(|(_, v)| v.parse().ok())
        .unwrap_or(0);
    let mut body = buf[head_end..].to_vec();
    while body.len() < len {
        let n = s.read(&mut tmp).ok()?;
        if n == 0 {
            break;
        }
        body.extend_from_slice(&tmp[..n]);
    }
    Some(Req {
        method,
        path,
        headers,
        body,
    })
}

/// `respond` maps a request to (status, json body).
pub fn start(respond: impl Fn(&Req) -> (u16, String) + Send + Sync + 'static) -> Mock {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = seen.clone();
    let respond = Arc::new(respond);
    thread::spawn(move || {
        for conn in listener.incoming() {
            let Ok(mut s) = conn else { continue };
            let (log, respond) = (log.clone(), respond.clone());
            thread::spawn(move || {
                while let Some(req) = read_request(&mut s) {
                    let (code, body) = respond(&req);
                    log.lock().unwrap().push(req);
                    let reason = if code < 300 { "OK" } else { "Error" };
                    let resp = format!("HTTP/1.1 {code} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: keep-alive\r\n\r\n{body}", body.len());
                    if s.write_all(resp.as_bytes()).is_err() {
                        break;
                    }
                }
            });
        }
    });
    Mock { url, seen }
}

/// Behaves like the real backend's happy path.
pub fn backend_ok(req: &Req) -> (u16, String) {
    match (req.method.as_str(), req.path.as_str()) {
        ("GET", "/api/health") => (200, r#"{"status":"ok"}"#.into()),
        ("POST", "/api/meetings") => (201, r#"{"id":"abc123"}"#.into()),
        ("PUT", p) if p.starts_with("/api/meetings/abc123/audio/") => {
            (201, r#"{"bytes":1}"#.into())
        }
        ("POST", "/api/meetings/abc123/finish") | ("POST", "/api/meetings/abc123/process") => {
            (200, "{}".into())
        }
        _ => (404, r#"{"detail":"tidak ada"}"#.into()),
    }
}
