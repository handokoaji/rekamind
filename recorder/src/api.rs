//! Talking to the Rekamind backend (local or remote). Plain blocking HTTP: this runs only
//! after the meeting, so it never competes with the recording.

use std::fs::File;
use std::path::Path;
use std::time::Duration;

use serde_json::{json, Value};

use crate::Source;

/// Shown when the server rejects our credentials.
pub const SESSION_EXPIRED: &str =
    "Sesi login berakhir. Masuk lagi di Rekamind, lalu coba unggah ulang";

pub struct Client {
    base: String,
    token: Option<String>,
    agent: ureq::Agent,
}

#[derive(Debug)]
pub struct ApiError(pub String);
impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ApiError {}

fn err(e: ureq::Error) -> ApiError {
    match e {
        ureq::Error::StatusCode(code) => {
            ApiError(format!("server menolak permintaan (HTTP {code})"))
        }
        other => ApiError(format!("tidak bisa menghubungi server: {other}")),
    }
}

impl Client {
    pub fn new(base: &str, token: Option<String>) -> Self {
        let builder = ureq::Agent::config_builder()
            .timeout_connect(Some(Duration::from_secs(10)))
            // ~6 requests per recording: connection reuse buys nothing, and a pooled connection the
            // server has since closed (uvicorn drops idle ones after ~5 s) fails with "Peer disconnected".
            .max_idle_connections(0)
            .max_idle_connections_per_host(0)
            .http_status_as_error(false); // read the server's own message instead of a bare code
        #[cfg(windows)]
        let builder = builder.tls_config(
            ureq::tls::TlsConfig::builder()
                .provider(ureq::tls::TlsProvider::NativeTls)
                .build(),
        );
        let agent: ureq::Agent = builder.build().into();
        Self {
            base: base.trim_end_matches('/').to_string(),
            token,
            agent,
        }
    }

    fn auth(&self) -> Option<String> {
        self.token.as_ref().map(|t| format!("Bearer {t}"))
    }

    fn read(mut resp: ureq::http::Response<ureq::Body>) -> Result<Value, ApiError> {
        let status = resp.status().as_u16();
        let body: Value = resp.body_mut().read_json().unwrap_or(Value::Null);
        if (200..300).contains(&status) {
            return Ok(body);
        }
        if status == 401 {
            // The one failure the user can act on, so say exactly what to do. Matched by the UI and
            // the controller (a recording is never discarded for this: it stays on disk).
            return Err(ApiError(SESSION_EXPIRED.into()));
        }
        let detail = body
            .get("detail")
            .and_then(Value::as_str)
            .unwrap_or("permintaan gagal");
        Err(ApiError(format!("{detail} (HTTP {status})")))
    }

    fn post(&self, path: &str, body: Option<Value>) -> Result<Value, ApiError> {
        let url = match path.strip_prefix("/../") {
            Some(p) => format!("{}/{p}", self.base), // outside /api
            None => format!("{}/api{path}", self.base),
        };
        let mut req = self.agent.post(url);
        if let Some(a) = self.auth() {
            req = req.header("authorization", a);
        }
        let resp = match body {
            Some(b) => req.send_json(b),
            None => req.send_empty(),
        }
        .map_err(err)?;
        Self::read(resp)
    }

    /// Trade the one-time loopback code (plus the PKCE verifier) for a Rekamind token.
    pub fn desktop_token(
        &self,
        code: &str,
        verifier: &str,
    ) -> Result<crate::login::Token, ApiError> {
        let v = self.post(
            "/../auth/desktop/token",
            Some(json!({ "code": code, "verifier": verifier })),
        )?;
        crate::login::parse_token(&v)
    }

    pub fn logout(&self) -> Result<(), ApiError> {
        self.post("/../auth/logout", None).map(|_| ())
    }

    pub fn health(&self) -> Result<(), ApiError> {
        let resp = self
            .agent
            .get(format!("{}/api/health", self.base))
            .call()
            .map_err(err)?;
        Self::read(resp).map(|_| ())
    }

    /// Is anything still queued or being processed? (Used to decide when a local backend may be shut down.)
    pub fn has_active_jobs(&self) -> Result<bool, ApiError> {
        let mut req = self
            .agent
            .get(format!("{}/api/meetings?limit=200", self.base));
        if let Some(a) = self.auth() {
            req = req.header("authorization", a);
        }
        let v = Self::read(req.call().map_err(err)?)?;
        Ok(v.as_array()
            .is_some_and(|ms| ms.iter().any(|m| !m.get("job").is_none_or(Value::is_null))))
    }

    pub fn create_meeting(
        &self,
        title: &str,
        language: &str,
        local_user_name: Option<&str>,
    ) -> Result<String, ApiError> {
        let v = self.post(
            "/meetings",
            Some(
                json!({ "title": title, "language": language, "local_user_name": local_user_name }),
            ),
        )?;
        v.get("id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(|| ApiError("respons server tidak memuat id rapat".into()))
    }

    pub fn upload(&self, meeting_id: &str, source: Source, path: &Path) -> Result<(), ApiError> {
        let len = std::fs::metadata(path)
            .map_err(|e| ApiError(format!("{}: {e}", path.display())))?
            .len();
        let mut file =
            File::open(path).map_err(|e| ApiError(format!("{}: {e}", path.display())))?;
        self.upload_reader(&mut file, len, meeting_id, source)
    }

    /// Stream `len` bytes from `reader`. Streamed, never buffered: a two-hour recording is not held in memory.
    pub fn upload_reader(
        &self,
        reader: &mut dyn std::io::Read,
        len: u64,
        meeting_id: &str,
        source: Source,
    ) -> Result<(), ApiError> {
        let mut req = self
            .agent
            .put(format!(
                "{}/api/meetings/{meeting_id}/audio/{}",
                self.base,
                source.api_name()
            ))
            .header("content-type", "audio/wav")
            .header("content-length", len.to_string());
        if let Some(a) = self.auth() {
            req = req.header("authorization", a);
        }
        let resp = req.send(ureq::SendBody::from_reader(reader)).map_err(err)?;
        Self::read(resp).map(|_| ())
    }

    pub fn finish(&self, meeting_id: &str) -> Result<(), ApiError> {
        self.post(&format!("/meetings/{meeting_id}/finish"), None)
            .map(|_| ())
    }

    pub fn process(&self, meeting_id: &str) -> Result<(), ApiError> {
        self.post(&format!("/meetings/{meeting_id}/process"), None)
            .map(|_| ())
    }
}
