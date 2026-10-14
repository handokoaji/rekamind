//! Signing in from the desktop app, without the app ever holding a Google secret.
//!
//! 1. The app makes a random PKCE `verifier` and listens on a loopback port.
//! 2. The system browser opens the SERVER's /auth/login (not Google directly), carrying the port
//!    and the challenge. The server runs the real Google login with its own client secret.
//! 3. The server redirects the browser to `http://127.0.0.1:<port>/callback?code=<one-time code>`.
//! 4. The app trades that code plus the verifier for a Rekamind token. A code intercepted by another
//!    local process is useless: only the verifier, which never left this process, redeems it.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::api::ApiError;

pub fn random_urlsafe(bytes: usize) -> String {
    let mut b = vec![0u8; bytes];
    getrandom::fill(&mut b).expect("the operating system must provide randomness");
    URL_SAFE_NO_PAD.encode(b)
}

/// RFC 7636 S256: BASE64URL(SHA256(verifier)) without padding.
pub fn challenge_for(verifier: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()))
}

pub struct PendingLogin {
    pub url: String,
    pub verifier: String,
    listener: TcpListener,
}

#[derive(Debug, Clone)]
pub struct Token {
    pub access_token: String,
    pub expires_at: String,
    pub email: String,
}

impl PendingLogin {
    /// Bind the loopback port and build the URL to open in a browser.
    pub fn begin(server: &str) -> std::io::Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0")?; // loopback only: unreachable from the network
        let port = listener.local_addr()?.port();
        let verifier = random_urlsafe(48); // 64 chars, within the 43..128 PKCE range
        let url = format!(
            "{}/auth/login?client=desktop&port={port}&cc={}",
            server.trim_end_matches('/'),
            challenge_for(&verifier)
        );
        Ok(Self {
            url,
            verifier,
            listener,
        })
    }

    pub fn port(&self) -> u16 {
        self.listener.local_addr().map(|a| a.port()).unwrap_or(0)
    }

    /// Wait for the browser to arrive at /callback and return the code. Other requests (favicon,
    /// probes) are answered and ignored.
    pub fn wait_for_code(&self, timeout: Duration) -> Result<String, String> {
        self.listener
            .set_nonblocking(true)
            .map_err(|e| e.to_string())?;
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            match self.listener.accept() {
                Ok((stream, _)) => {
                    if let Some(result) = handle(stream) {
                        return result;
                    }
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(50))
                }
                Err(e) => return Err(e.to_string()),
            }
        }
        Err("Waktu habis menunggu login di browser.".into())
    }
}

fn respond(stream: &mut TcpStream, status: &str, title: &str, body: &str) {
    let html = format!(
        "<!doctype html><html lang=\"id\"><meta charset=\"utf-8\"><title>{title}</title>\
         <body style=\"font-family:system-ui,sans-serif;max-width:30rem;margin:4rem auto;padding:0 1rem\"><h1 style=\"font-size:1.25rem\">{title}</h1><p>{body}</p></body></html>"
    );
    let _ = write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{html}",
        html.len()
    );
}

/// None = not the request we are waiting for. Some(result) = done.
fn handle(mut stream: TcpStream) -> Option<Result<String, String>> {
    stream.set_nonblocking(false).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    let mut buf = [0u8; 4096];
    let n = stream.read(&mut buf).ok()?;
    let head = String::from_utf8_lossy(&buf[..n]);
    let line = head.lines().next()?;
    let mut parts = line.split_whitespace();
    let (method, target) = (parts.next()?, parts.next()?);
    let (path, query) = target.split_once('?').unwrap_or((target, ""));
    if method != "GET" || path != "/callback" {
        respond(
            &mut stream,
            "404 Not Found",
            "Tidak ditemukan",
            "Halaman ini tidak ada.",
        );
        return None;
    }
    let mut code = None;
    let mut error = None;
    for pair in query.split('&') {
        match pair.split_once('=') {
            Some(("code", v)) => code = Some(v.to_string()),
            Some(("error", v)) => error = Some(v.to_string()),
            _ => {}
        }
    }
    if let (Some(code), None) = (&code, &error) {
        respond(
            &mut stream,
            "200 OK",
            "Login berhasil",
            "Anda boleh menutup tab ini dan kembali ke Rekamind.",
        );
        return Some(Ok(code.clone()));
    }
    respond(
        &mut stream,
        "400 Bad Request",
        "Login gagal",
        "Kembali ke Rekamind dan coba lagi.",
    );
    Some(Err("Login dibatalkan atau ditolak.".into()))
}

pub fn parse_token(v: &Value) -> Result<Token, ApiError> {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_owned);
    match (s("access_token"), s("expires_at")) {
        (Some(access_token), Some(expires_at)) => Ok(Token {
            access_token,
            expires_at,
            email: v
                .pointer("/user/email")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        }),
        _ => Err(ApiError("respons login dari server tidak lengkap".into())),
    }
}

/// Where the token lives between launches. The real implementation is the OS credential store;
/// tests use memory. A token is as sensitive as a password: never a plain file.
pub trait TokenStore: Send + Sync {
    fn load(&self) -> Option<String>;
    fn save(&self, token: &str) -> Result<(), String>;
    fn clear(&self);
}

#[derive(Default)]
pub struct MemoryStore(std::sync::Mutex<Option<String>>);

impl TokenStore for MemoryStore {
    fn load(&self) -> Option<String> {
        self.0.lock().unwrap().clone()
    }
    fn save(&self, token: &str) -> Result<(), String> {
        *self.0.lock().unwrap() = Some(token.to_string());
        Ok(())
    }
    fn clear(&self) {
        *self.0.lock().unwrap() = None;
    }
}
