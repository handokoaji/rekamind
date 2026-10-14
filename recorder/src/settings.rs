//! The desktop app's settings: validated, persisted atomically, and turned into the controller's
//! config and the on-demand local backend. No GUI types here, so it is all unit-tested.

use std::fs;
use std::path::Path;
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::controller::Config;
use crate::local_backend::LocalBackend;

/// Origins the bundled UI is served from (Linux/macOS vs Windows webviews). A local backend must
/// allow them or the UI's own requests would be blocked by CORS.
pub const UI_ORIGINS: &str = "tauri://localhost,http://tauri.localhost,https://tauri.localhost";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct Settings {
    /// "local": the backend runs on this computer, started on demand. "remote": a server elsewhere.
    pub mode: String,
    pub server: String,
    pub local_program: String,
    pub local_args: Vec<String>,
    pub local_port: u16,
    pub language: String,
    pub local_user_name: String,
    pub auto_process: bool,
    /// Global shortcut that starts/stops recording from any app.
    pub hotkey: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            mode: "local".into(),
            server: String::new(),
            local_program: "python".into(),
            local_args: vec!["-m".into(), "rekamind_server".into()],
            local_port: 8787,
            language: "id".into(),
            local_user_name: String::new(),
            auto_process: true,
            hotkey: "CmdOrCtrl+Alt+R".into(),
        }
    }
}

/// Normalises to an origin and accepts only http(s): a typo or hostile value must not be able to
/// point uploads at another scheme.
pub fn normalize_server(raw: &str) -> Option<String> {
    let v = raw.trim();
    let (scheme, rest) = v.split_once("://")?;
    if scheme != "http" && scheme != "https" {
        return None;
    }
    let host = rest.split(['/', '?', '#']).next().unwrap_or("");
    if host.is_empty() || host.contains(char::is_whitespace) || host.contains('@') {
        return None;
    }
    Some(format!("{scheme}://{host}"))
}

impl Settings {
    /// Returns the cleaned settings, or a message the user can act on.
    pub fn validated(mut self) -> Result<Self, String> {
        match self.mode.as_str() {
            "local" => {
                if self.local_program.trim().is_empty() {
                    return Err("Isi program untuk menyalakan mesin pemrosesan lokal.".into());
                }
                if self.local_port < 1024 {
                    return Err("Port harus 1024 atau lebih.".into());
                }
            }
            "remote" => {
                self.server = normalize_server(&self.server)
                    .ok_or("Alamat server harus diawali http:// atau https://")?;
            }
            _ => return Err("Mode harus 'local' atau 'remote'.".into()),
        }
        if !["id", "en"].contains(&self.language.as_str()) {
            return Err("Bahasa tidak dikenal.".into());
        }
        if self.hotkey.trim().is_empty() {
            return Err("Pintasan keyboard tidak boleh kosong.".into());
        }
        self.local_user_name = self.local_user_name.trim().chars().take(100).collect();
        Ok(self)
    }

    /// Where the UI and the uploader talk to.
    pub fn server_url(&self) -> String {
        if self.mode == "local" {
            format!("http://127.0.0.1:{}", self.local_port)
        } else {
            self.server.clone()
        }
    }

    pub fn to_config(&self) -> Config {
        Config {
            server: Some(self.server_url()).filter(|s| !s.is_empty()),
            token: None,
            language: self.language.clone(),
            local_user_name: Some(self.local_user_name.clone()).filter(|s| !s.is_empty()),
            auto_process: self.auto_process,
        }
    }

    pub fn local_backend(&self) -> Option<Arc<LocalBackend>> {
        if self.mode != "local" {
            return None;
        }
        let env = vec![
            ("REKAMIND_HOST".to_string(), "127.0.0.1".to_string()),
            ("REKAMIND_PORT".to_string(), self.local_port.to_string()),
            ("REKAMIND_CORS_ORIGINS".to_string(), UI_ORIGINS.to_string()),
        ];
        Some(Arc::new(LocalBackend::new(
            self.local_program.clone(),
            self.local_args.clone(),
            env,
            self.server_url(),
        )))
    }

    /// Missing or unreadable file -> defaults; a corrupt file must never stop the app from opening.
    pub fn load(path: &Path) -> Self {
        fs::read_to_string(path)
            .ok()
            .and_then(|s| serde_json::from_str::<Settings>(&s).ok())
            .and_then(|s| s.validated().ok())
            .unwrap_or_default()
    }

    /// Write-then-rename so a crash mid-save cannot leave half a file.
    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let tmp = path.with_extension("json.tmp");
        fs::write(
            &tmp,
            serde_json::to_vec_pretty(self).map_err(std::io::Error::other)?,
        )?;
        fs::rename(tmp, path)
    }
}
