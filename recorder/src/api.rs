//! Talking to the Rekamind backend (local or remote). Plain blocking HTTP: this runs only
//! after the meeting, so it never competes with the recording.

use std::fs::File;
use std::path::Path;
use std::time::Duration;

use serde_json::{json, Value};

use crate::Source;

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
        let detail = body
            .get("detail")
            .and_then(Value::as_str)
            .unwrap_or("permintaan gagal");
        Err(ApiError(format!("{detail} (HTTP {status})")))
    }

    fn post(&self, path: &str, body: Option<Value>) -> Result<Value, ApiError> {
        let mut req = self.agent.post(format!("{}/api{path}", self.base));
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

    pub fn health(&self) -> Result<(), ApiError> {
        let resp = self
            .agent
            .get(format!("{}/api/health", self.base))
            .call()
            .map_err(err)?;
        Self::read(resp).map(|_| ())
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
        let file = File::open(path).map_err(|e| ApiError(format!("{}: {e}", path.display())))?;
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
        // Streamed from disk: a two-hour recording is never held in memory.
        let resp = req.send(file).map_err(err)?;
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
