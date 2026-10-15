//! The desktop app's settings: validated, persisted atomically, and turned into the controller's
//! config and the on-demand local backend. No GUI types here, so it is all unit-tested.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::controller::Config;
use crate::engines::EngineTool;
use crate::local_backend::LocalBackend;

/// A fresh secret for each launch of the app: it lives in memory here and in the backend's environment,
/// and nowhere else.
pub fn new_local_token() -> String {
    crate::login::random_urlsafe(32)
}

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
    // --- processing (used by the local backend only) ---
    /// A faster-whisper model name (large-v3, medium, small...) or a folder.
    pub whisper_model: String,
    /// auto | cuda | cpu
    pub whisper_device: String,
    /// none (one "speaker" per source) | pyannote (needs the diarize pack and a Hugging Face token)
    pub diarizer: String,
    /// Any OpenAI-compatible endpoint that writes the summary and the tasks.
    pub llm_base_url: String,
    pub llm_model: String,
    /// Names and jargon fed to Whisper as a prompt.
    pub glossary: String,
}

/// What the backend needs from the app each time it starts. Secrets live in the OS credential
/// store and only ever travel as environment variables of the child process.
pub struct BackendEnv<'a> {
    pub token: &'a str,
    pub data_dir: &'a Path,
    pub engines_ready: bool,
    pub llm_api_key: Option<&'a str>,
    pub hf_token: Option<&'a str>,
    /// The backend shipped inside the installer, if this build has one.
    pub bundled: Option<&'a Path>,
}

impl BackendEnv<'_> {
    pub fn pack_dir(&self) -> PathBuf {
        self.data_dir.join("engine-pack")
    }
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            mode: "local".into(),
            server: String::new(),
            // "auto": the backend bundled with the installer, else `python -m rekamind_server`.
            local_program: "auto".into(),
            local_args: Vec::new(),
            local_port: 8787,
            language: "id".into(),
            local_user_name: String::new(),
            auto_process: true,
            hotkey: "CmdOrCtrl+Alt+R".into(),
            whisper_model: "large-v3".into(),
            whisper_device: "auto".into(),
            diarizer: "none".into(),
            llm_base_url: "https://api.groq.com/openai/v1".into(),
            llm_model: "openai/gpt-oss-120b".into(),
            glossary: String::new(),
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
        if !["auto", "cuda", "cpu", "intel"].contains(&self.whisper_device.as_str()) {
            return Err("Perangkat Whisper harus auto, cuda, cpu, atau intel.".into());
        }
        if !["none", "pyannote"].contains(&self.diarizer.as_str()) {
            return Err("Pemisah pembicara harus 'none' atau 'pyannote'.".into());
        }
        self.whisper_model = self.whisper_model.trim().to_string();
        if self.whisper_model.is_empty() || self.whisper_model.chars().count() > 200 {
            return Err("Nama model Whisper tidak valid.".into());
        }
        self.llm_model = self.llm_model.trim().to_string();
        if self.llm_model.is_empty() || self.llm_model.chars().count() > 200 {
            return Err("Nama model ringkasan tidak valid.".into());
        }
        let base = self.llm_base_url.trim().trim_end_matches('/').to_string();
        let ok_scheme = base.starts_with("http://") || base.starts_with("https://");
        if !ok_scheme || base.contains(char::is_whitespace) || base.contains('@') {
            return Err("Alamat layanan ringkasan harus diawali http:// atau https://".into());
        }
        self.llm_base_url = base;
        self.glossary = self.glossary.chars().take(2000).collect();
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

    /// `token` is the credential for the chosen server: the per-launch secret for a local backend,
    /// or the signed-in user's token for a remote one.
    pub fn to_config(&self, token: Option<&str>) -> Config {
        Config {
            server: Some(self.server_url()).filter(|s| !s.is_empty()),
            token: token.map(str::to_owned),
            language: self.language.clone(),
            local_user_name: Some(self.local_user_name.clone()).filter(|s| !s.is_empty()),
            auto_process: self.auto_process,
        }
    }

    /// What to run: (program, args for the backend, args that select the `engines` command).
    pub fn launch(&self, bundled: Option<&Path>) -> (String, Vec<String>, Vec<String>) {
        let python_engines = vec!["-m".to_string(), "rekamind_server.enginepack".to_string()];
        if self.local_program == "auto" {
            return match bundled {
                Some(p) => (
                    p.to_string_lossy().into_owned(),
                    vec![],
                    vec!["engines".into()],
                ),
                None => (
                    "python".into(),
                    vec!["-m".into(), "rekamind_server".into()],
                    python_engines,
                ),
            };
        }
        (
            self.local_program.clone(),
            self.local_args.clone(),
            python_engines,
        )
    }

    /// Environment for the child process (backend and engine tool alike).
    pub fn backend_env(&self, e: &BackendEnv) -> Vec<(String, String)> {
        let mut env = vec![
            // Single user, no Google login, loopback only, and every request must carry this secret.
            ("REKAMIND_AUTH".to_string(), "local_token".to_string()),
            ("REKAMIND_LOCAL_TOKEN".to_string(), e.token.to_string()),
            ("REKAMIND_HOST".to_string(), "127.0.0.1".to_string()),
            ("REKAMIND_PORT".to_string(), self.local_port.to_string()),
            ("REKAMIND_CORS_ORIGINS".to_string(), UI_ORIGINS.to_string()),
            // The backend exits by itself if this app dies without cleaning up (crash, kill -9).
            (
                "REKAMIND_PARENT_PID".to_string(),
                std::process::id().to_string(),
            ),
            (
                "REKAMIND_DATA_DIR".to_string(),
                e.data_dir.to_string_lossy().into_owned(),
            ),
            (
                "REKAMIND_ENGINE_PACK".to_string(),
                e.pack_dir().to_string_lossy().into_owned(),
            ),
            // Model weights live with the app's data, not in a hidden per-user cache.
            (
                "HF_HOME".to_string(),
                e.data_dir.join("models").to_string_lossy().into_owned(),
            ),
            (
                "REKAMIND_ENGINES".to_string(),
                if e.engines_ready { "local" } else { "none" }.to_string(),
            ),
            ("REKAMIND_LANGUAGE".to_string(), self.language.clone()),
            (
                "REKAMIND_WHISPER_MODEL".to_string(),
                self.whisper_model.clone(),
            ),
            (
                "REKAMIND_WHISPER_DEVICE".to_string(),
                self.whisper_device.clone(),
            ),
            ("REKAMIND_DIARIZER".to_string(), self.diarizer.clone()),
            (
                "REKAMIND_LLM_BASE_URL".to_string(),
                self.llm_base_url.clone(),
            ),
            ("REKAMIND_LLM_MODEL".to_string(), self.llm_model.clone()),
            ("REKAMIND_GLOSSARY".to_string(), self.glossary.clone()),
        ];
        if let Some(k) = e.llm_api_key.filter(|k| !k.is_empty()) {
            env.push(("REKAMIND_LLM_API_KEY".into(), k.to_string()));
        }
        if let Some(t) = e.hf_token.filter(|t| !t.is_empty()) {
            env.push(("REKAMIND_HF_TOKEN".into(), t.to_string()));
        }
        env
    }

    /// The on-demand local backend, or None when a remote server is selected.
    pub fn local_backend(&self, e: &BackendEnv) -> Option<Arc<LocalBackend>> {
        if self.mode != "local" {
            return None;
        }
        let (program, args, _) = self.launch(e.bundled);
        Some(Arc::new(
            LocalBackend::new(program, args, self.backend_env(e), self.server_url())
                .with_token(e.token)
                .with_log(e.data_dir.join("logs").join("backend.log")),
        ))
    }

    /// The same program, asked to manage the engine pack. Works in either mode (the pack is local).
    pub fn engine_tool(&self, e: &BackendEnv) -> EngineTool {
        let (program, _, prefix) = self.launch(e.bundled);
        EngineTool {
            program,
            prefix,
            env: self.backend_env(e),
        }
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
