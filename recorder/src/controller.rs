//! The desktop shell's brain, with no GUI in it: start/stop, live status, upload with progress,
//! and recovery of recordings that never reached the server. The Tauri layer only forwards
//! calls to this and renders `UiState`, so everything here is testable without a window.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::api::Client;
use crate::backend::Backend;
use crate::local_backend::LocalBackend;
use crate::session::{self, Finished, Session};
use crate::sink::SourceState;
use crate::uploader::{self, Meta};
use crate::Source;

type Observer = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

const META_FILE: &str = "meeting.json";
const UPLOADED_FILE: &str = "uploaded.json";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Config {
    /// Backend base URL. None = not set up yet: recordings are kept, nothing is uploaded.
    pub server: Option<String>,
    pub token: Option<String>,
    pub language: String,
    pub local_user_name: Option<String>,
    pub auto_process: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server: None,
            token: None,
            language: "id".into(),
            local_user_name: None,
            auto_process: true,
        }
    }
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Idle,
    Recording,
    Uploading,
    /// Uploaded (and queued for processing if configured).
    Done,
    /// Recorded and safe on disk, but not on the server. Shown with a Retry.
    NeedsAttention,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SourceView {
    pub source: &'static str,
    pub label: &'static str,
    pub level: f32,
    /// recording | reconnecting | unavailable | failed
    pub state: &'static str,
    pub message: Option<String>,
    pub seconds: f64,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct UploadView {
    pub step: String,
    pub fraction: f32,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Outcome {
    pub title: String,
    pub dir: String,
    pub meeting_id: Option<String>,
    pub error: Option<String>,
    pub warnings: Vec<String>,
    /// Uploaded fine, but the server refused to start processing (engines not installed, no API key...).
    pub not_processed: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Pending {
    pub dir: String,
    pub title: String,
    pub created_unix: u64,
    /// True when the app died mid-recording; the audio was repaired and is ready to upload.
    pub crashed: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct UiState {
    pub phase: Phase,
    pub title: Option<String>,
    pub elapsed_secs: f64,
    pub sources: Vec<SourceView>,
    pub upload: Option<UploadView>,
    pub last: Option<Outcome>,
    pub pending: Vec<Pending>,
}

#[derive(Serialize, Deserialize)]
struct SavedMeta {
    title: String,
    language: String,
    local_user_name: Option<String>,
    created_unix: u64,
}

struct Active {
    session: Session,
    title: String,
}

#[derive(Default)]
struct Inner {
    active: Option<Active>,
    uploading: Option<UploadView>,
    last: Option<Outcome>,
}

pub struct Controller {
    root: PathBuf,
    backend: Box<dyn Fn() -> Box<dyn Backend> + Send + Sync>,
    config: Mutex<Config>,
    inner: Arc<Mutex<Inner>>,
    /// When set, the backend is started on demand before an upload and left to the idle watcher to stop.
    local: Mutex<Option<Arc<LocalBackend>>>,
    /// Called on every phase change (start, stop, upload finished) so a shell can update its tray/UI.
    observer: Observer,
    /// Uploads run one at a time (the status slot is single); this counts those queued or running.
    uploads: Arc<AtomicUsize>,
    upload_lock: Arc<Mutex<()>>,
    /// Tests substitute this so retries don't sleep for real.
    sleeper: Arc<dyn Fn(Duration) + Send + Sync>,
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn read_meta(dir: &Path) -> Option<SavedMeta> {
    serde_json::from_str(&fs::read_to_string(dir.join(META_FILE)).ok()?).ok()
}

/// Two spellings of the same folder (symlink, `\\?\` prefix and 8.3 names on Windows, `..`) must compare
/// equal: this guards "never delete or list the recording that is still being written".
fn same_dir(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(x), Ok(y)) => x == y,
        _ => a == b,
    }
}

fn files_in(dir: &Path) -> Vec<(Source, PathBuf)> {
    Source::ALL
        .into_iter()
        .map(|s| (s, dir.join(s.file_name())))
        .filter(|(_, p)| p.is_file())
        .collect()
}

fn view(source: Source, level: f32, state: &SourceState, seconds: f64) -> SourceView {
    let (state, message) = match state {
        SourceState::Recording => ("recording", None),
        SourceState::Reconnecting => (
            "reconnecting",
            Some("Perangkat terputus, mencoba tersambung lagi…".to_string()),
        ),
        SourceState::Unavailable(m) => ("unavailable", Some(m.clone())),
        SourceState::Failed(m) => ("failed", Some(m.clone())),
    };
    SourceView {
        source: source.api_name(),
        label: source.label(),
        level,
        state,
        message,
        seconds,
    }
}

impl Controller {
    pub fn new(
        root: PathBuf,
        config: Config,
        backend: impl Fn() -> Box<dyn Backend> + Send + Sync + 'static,
    ) -> Self {
        Self {
            root,
            backend: Box::new(backend),
            config: Mutex::new(config),
            inner: Arc::default(),
            local: Mutex::new(None),
            observer: Arc::default(),
            uploads: Arc::default(),
            upload_lock: Arc::default(),
            sleeper: Arc::new(std::thread::sleep),
        }
    }

    pub fn with_local_backend(self, b: Arc<LocalBackend>) -> Self {
        self.set_local_backend(Some(b));
        self
    }

    /// Swap (or remove) the on-demand local backend, e.g. after the user changes settings.
    pub fn set_local_backend(&self, b: Option<Arc<LocalBackend>>) {
        *self.local.lock().unwrap() = b;
    }

    pub fn local_backend(&self) -> Option<Arc<LocalBackend>> {
        self.local.lock().unwrap().clone()
    }

    /// Start the on-demand local backend, unless a recording is running. This is an invariant, not
    /// a courtesy: nothing heavy may become resident during a meeting, whoever asks (the UI's
    /// status poll can race with the start of a recording and would otherwise bring it right back).
    pub fn ensure_backend(&self, timeout: Duration) -> Result<(), String> {
        let Some(l) = self.local_backend() else {
            return Ok(());
        };
        // Held for the whole call so a recording cannot start between the check and the spawn.
        let inner = self.inner.lock().unwrap();
        if inner.active.is_some() {
            return Err("Layanan pemrosesan lokal tidak dinyalakan selama merekam.".into());
        }
        drop(inner);
        l.ensure(timeout)
    }

    pub fn set_observer(&self, f: impl Fn() + Send + Sync + 'static) {
        *self.observer.lock().unwrap() = Some(Arc::new(f));
    }

    fn notify(observer: &Mutex<Option<Arc<dyn Fn() + Send + Sync>>>) {
        let f = observer.lock().unwrap().clone();
        if let Some(f) = f {
            f();
        }
    }

    pub fn with_sleeper(mut self, f: impl Fn(Duration) + Send + Sync + 'static) -> Self {
        self.sleeper = Arc::new(f);
        self
    }

    pub fn config(&self) -> Config {
        self.config.lock().unwrap().clone()
    }
    pub fn set_config(&self, c: Config) {
        *self.config.lock().unwrap() = c;
    }

    pub fn is_recording(&self) -> bool {
        self.inner.lock().unwrap().active.is_some()
    }

    pub fn start(&self, title: &str) -> Result<(), String> {
        let mut inner = self.inner.lock().unwrap();
        if inner.active.is_some() {
            return Err("Perekaman sedang berjalan.".into());
        }
        let title = if title.trim().is_empty() {
            "Rapat tanpa judul".to_string()
        } else {
            title.trim().to_string()
        };
        let dir = self.root.join(format!("rapat-{}", now_unix()));
        let cfg = self.config();
        let backend = (self.backend)();
        // Nothing heavy may be resident while a meeting is being recorded.
        if let Some(l) = self.local_backend() {
            l.stop_if_idle();
        }
        let session =
            Session::start(backend.as_ref(), &dir, &Source::ALL).map_err(|e| e.to_string())?;
        // Saved first thing, so a crash still knows what to call the meeting when it is recovered.
        let meta = SavedMeta {
            title: title.clone(),
            language: cfg.language,
            local_user_name: cfg.local_user_name,
            created_unix: now_unix(),
        };
        let _ = fs::write(
            dir.join(META_FILE),
            serde_json::to_string(&meta).unwrap_or_default(),
        );
        inner.last = None;
        inner.active = Some(Active { session, title });
        drop(inner);
        Self::notify(&self.observer);
        Ok(())
    }

    /// Finish recording and, if a server is configured, upload in the background.
    pub fn stop(&self) -> Result<(), String> {
        let active = self
            .inner
            .lock()
            .unwrap()
            .active
            .take()
            .ok_or("Tidak sedang merekam.")?;
        let fin = active.session.stop();
        self.after_recording(active.title, fin);
        Self::notify(&self.observer);
        Ok(())
    }

    /// App is quitting: close the files properly but do not start an upload we cannot finish.
    pub fn stop_for_quit(&self) {
        if let Some(a) = self.inner.lock().unwrap().active.take() {
            let _ = a.session.stop();
        }
    }

    fn after_recording(&self, title: String, fin: Finished) {
        let dir = fin.dir.to_string_lossy().into_owned();
        if fin.files.is_empty() {
            self.inner.lock().unwrap().last = Some(Outcome {
                title,
                dir,
                meeting_id: None,
                error: Some("Tidak ada audio yang terekam.".into()),
                warnings: fin.warnings,
                not_processed: None,
            });
            return;
        }
        let cfg = self.config();
        if cfg.server.is_none() {
            self.inner.lock().unwrap().last = Some(Outcome {
                title, dir, meeting_id: None, warnings: fin.warnings, not_processed: None,
                error: Some("Alamat server belum diatur. Rekaman tersimpan di komputer ini dan bisa diunggah nanti.".into()),
            });
            return;
        }
        self.spawn_upload(fin.dir, title, fin.warnings);
    }

    /// Upload a recording that is already on disk (after a failure, or one left by a crash).
    pub fn retry_upload(&self, dir: &Path) -> Result<(), String> {
        let dir = self.inside_root(dir)?;
        if self.inner.lock().unwrap().uploading.is_some() {
            return Err("Unggahan lain sedang berjalan.".into());
        }
        session::recover_dir(&dir).map_err(|e| format!("tidak bisa memperbaiki rekaman: {e}"))?;
        let title = read_meta(&dir)
            .map(|m| m.title)
            .unwrap_or_else(|| "Rapat".into());
        self.spawn_upload(dir, title, vec![]);
        Ok(())
    }

    fn spawn_upload(&self, dir: PathBuf, title: String, warnings: Vec<String>) {
        let cfg = self.config();
        let saved = read_meta(&dir);
        let meta = Meta {
            title: title.clone(),
            language: saved
                .as_ref()
                .map(|m| m.language.clone())
                .unwrap_or(cfg.language.clone()),
            local_user_name: saved
                .and_then(|m| m.local_user_name)
                .or(cfg.local_user_name.clone()),
            process: cfg.auto_process,
        };
        self.inner.lock().unwrap().uploading = Some(UploadView {
            step: "menghubungi server".into(),
            fraction: 0.0,
        });
        let (inner, sleeper, local, observer) = (
            self.inner.clone(),
            self.sleeper.clone(),
            self.local_backend(),
            self.observer.clone(),
        );
        let (uploads, lock) = (self.uploads.clone(), self.upload_lock.clone());
        uploads.fetch_add(1, Ordering::SeqCst);
        std::thread::spawn(move || {
            let _one_at_a_time = lock.lock().unwrap();
            let fail = |inner: &Mutex<Inner>,
                        title: String,
                        dir: &Path,
                        warnings: Vec<String>,
                        e: String| {
                let mut g = inner.lock().unwrap();
                g.last = Some(Outcome {
                    title,
                    dir: dir.to_string_lossy().into_owned(),
                    meeting_id: None,
                    warnings,
                    not_processed: None,
                    error: Some(format!(
                        "{e}. Rekaman aman di komputer ini; coba lagi nanti."
                    )),
                });
            };
            let finish = |inner: &Mutex<Inner>| {
                if uploads.fetch_sub(1, Ordering::SeqCst) == 1 {
                    inner.lock().unwrap().uploading = None;
                }
                Controller::notify(&observer);
            };
            if let Some(l) = &local {
                // Heavy work waits for the meeting to end: if a new recording is running, hold off.
                loop {
                    let recording = inner.lock().unwrap().active.is_some();
                    inner.lock().unwrap().uploading = Some(UploadView {
                        step: if recording {
                            "menunggu rapat yang sedang direkam selesai"
                        } else {
                            "menyalakan mesin pemrosesan lokal"
                        }
                        .into(),
                        fraction: 0.0,
                    });
                    if recording {
                        std::thread::sleep(Duration::from_millis(500));
                        continue;
                    }
                    if let Err(e) = l.ensure(Duration::from_secs(90)) {
                        fail(&inner, title, &dir, warnings, e);
                        finish(&inner);
                        return;
                    }
                    // A recording may have started while the backend was coming up: back off, again.
                    if inner.lock().unwrap().active.is_some() {
                        l.stop_if_idle();
                        continue;
                    }
                    break;
                }
            }
            let client = Client::new(cfg.server.as_deref().unwrap_or_default(), cfg.token.clone());
            let files = files_in(&dir);
            let progress_inner = inner.clone();
            let res = uploader::upload_meeting(
                &client,
                &files,
                &meta,
                move |p| {
                    progress_inner.lock().unwrap().uploading = Some(UploadView {
                        step: p.step.into(),
                        fraction: p.fraction,
                    })
                },
                move |d| sleeper(d),
            );
            match res {
                Ok(up) => {
                    let id = up.id;
                    let _ = fs::write(
                        dir.join(UPLOADED_FILE),
                        format!("{{\"meeting_id\":\"{id}\"}}"),
                    );
                    inner.lock().unwrap().last = Some(Outcome {
                        title,
                        dir: dir.to_string_lossy().into_owned(),
                        meeting_id: Some(id),
                        error: None,
                        warnings,
                        not_processed: up.not_processed,
                    });
                }
                Err(e) => fail(&inner, title, &dir, warnings, e),
            }
            finish(&inner);
        });
    }

    /// Delete a recording folder. Only folders inside our own recordings root can ever be removed.
    pub fn discard(&self, dir: &Path) -> Result<(), String> {
        let dir = self.inside_root(dir)?;
        if self
            .inner
            .lock()
            .unwrap()
            .active
            .as_ref()
            .is_some_and(|a| same_dir(a.session.dir(), &dir))
        {
            return Err("Rekaman ini sedang berjalan.".into());
        }
        fs::remove_dir_all(&dir).map_err(|e| e.to_string())
    }

    fn inside_root(&self, dir: &Path) -> Result<PathBuf, String> {
        let root = self.root.canonicalize().map_err(|e| e.to_string())?;
        let d = dir
            .canonicalize()
            .map_err(|_| "Folder rekaman tidak ditemukan.".to_string())?;
        if d.parent() == Some(root.as_path()) {
            Ok(d)
        } else {
            Err("Folder di luar penyimpanan rekaman.".into())
        }
    }

    /// Recordings that never reached the server: finished-but-not-uploaded, or interrupted by a crash.
    pub fn scan_pending(&self) -> Vec<Pending> {
        let Ok(entries) = fs::read_dir(&self.root) else {
            return vec![];
        };
        let live = self
            .inner
            .lock()
            .unwrap()
            .active
            .as_ref()
            .map(|a| a.session.dir().to_path_buf());
        let is_live = |p: &Path| live.as_deref().is_some_and(|l| same_dir(l, p));
        let mut out: Vec<Pending> = entries
            .flatten()
            .map(|e| e.path())
            .filter(|p| {
                p.is_dir()
                    && !is_live(p)
                    && !p.join(UPLOADED_FILE).exists()
                    && !files_in(p).is_empty()
            })
            .map(|p| {
                let marker = fs::read_to_string(p.join(session::MARKER)).unwrap_or_default();
                let m = read_meta(&p);
                Pending {
                    dir: p.to_string_lossy().into_owned(),
                    title: m.as_ref().map(|m| m.title.clone()).unwrap_or_else(|| {
                        p.file_name()
                            .map(|n| n.to_string_lossy().into_owned())
                            .unwrap_or_default()
                    }),
                    created_unix: m.map(|m| m.created_unix).unwrap_or(0),
                    crashed: marker.contains("\"status\":\"recording\""),
                }
            })
            .collect();
        out.sort_by_key(|p| std::cmp::Reverse(p.created_unix));
        out
    }

    pub fn state(&self) -> UiState {
        let (mut st, uploading, last) = {
            let g = self.inner.lock().unwrap();
            let rec = g
                .active
                .as_ref()
                .map(|a| (a.title.clone(), a.session.status()));
            (rec, g.uploading.clone(), g.last.clone())
        };
        let pending = self.scan_pending();
        if let Some((title, s)) = st.take() {
            return UiState {
                phase: Phase::Recording,
                title: Some(title),
                elapsed_secs: s.elapsed.as_secs_f64(),
                sources: s
                    .sources
                    .iter()
                    .map(|x| view(x.source, x.level, &x.state, x.seconds))
                    .collect(),
                upload: None,
                last: None,
                pending,
            };
        }
        let phase = if uploading.is_some() {
            Phase::Uploading
        } else {
            match &last {
                Some(o) if o.error.is_some() => Phase::NeedsAttention,
                Some(_) => Phase::Done,
                None => Phase::Idle,
            }
        };
        UiState {
            phase,
            title: last.as_ref().map(|o| o.title.clone()),
            elapsed_secs: 0.0,
            sources: vec![],
            upload: uploading,
            last,
            pending,
        }
    }

    /// Dismiss the "done / needs attention" banner.
    pub fn clear_last(&self) {
        self.inner.lock().unwrap().last = None;
    }
}
