//! Rekamind desktop shell. All real logic lives in `rekamind-recorder` (tested without a GUI);
//! this file only wires it to the window, tray, global shortcut and notifications.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rekamind_recorder::backend::synthetic::{Script, SyntheticBackend};
use rekamind_recorder::backend::{default_backend, Backend};
use rekamind_recorder::controller::{Controller, Phase, UiState};
use rekamind_recorder::api::Client;
use rekamind_recorder::engines::EngineTool;
use rekamind_recorder::local_backend::{LocalBackend, Watcher};
use rekamind_recorder::login::{PendingLogin, TokenStore};
use rekamind_recorder::settings::{new_local_token, BackendEnv, Settings};
use rekamind_recorder::update::{self, Update};
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, Wry};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
use tauri_plugin_notification::NotificationExt;

const TRAY_IDLE: &[u8] = include_bytes!("../icons/tray-idle.png");
const TRAY_RECORDING: &[u8] = include_bytes!("../icons/tray-recording.png");
/// A local backend nobody is using for this long is shut down (frees RAM and the GPU).
const BACKEND_IDLE_AFTER: Duration = Duration::from_secs(10 * 60);

/// Prefix the UI recognises: the local backend is intentionally off while engines are being installed.
const ENGINE_BUSY: &str = "Pemasangan mesin sedang berjalan. Layanan lokal menyala lagi setelah selesai.";

struct Shared {
    ctl: Arc<Controller>,
    settings: Mutex<Settings>,
    settings_path: PathBuf,
    recordings: PathBuf,
    toggle_item: Mutex<Option<MenuItem<Wry>>>,
    /// False when the OS has no tray (some Linux desktops): then closing the window must quit.
    tray_ok: Mutex<bool>,
    last_phase: Mutex<Phase>,
    watcher: Mutex<Option<Watcher>>,
    hotkey_error: Mutex<Option<String>>,
    /// Per-launch secret for a local backend; never written to disk.
    local_token: String,
    store: Arc<dyn TokenStore>,
    /// Signed-in user's token for a remote server (None until they sign in).
    user_token: Mutex<Option<String>>,
    /// Backend data (SQLite, models, engine pack, logs) lives here, apart from the recordings.
    data_dir: PathBuf,
    /// The backend shipped inside the installer (None in a development checkout).
    bundled: Option<PathBuf>,
    /// Secrets for the local backend, kept in the OS credential store and mirrored here.
    llm_key: Mutex<Option<String>>,
    hf_token: Mutex<Option<String>>,
    /// The one long-running engine job (install / model download) and what it has printed so far,
    /// so a window opened mid-install sees the progress instead of an empty page.
    engine_job: Mutex<EngineJob>,
    engine_cancel: AtomicBool,
}

#[derive(Default, Clone, serde::Serialize)]
struct EngineJob {
    /// "install cpu", "warmup", ... while running.
    running: Option<String>,
    log: VecDeque<String>,
    /// Outcome of the last finished job: None = no job yet, Some(None) = ok, Some(Some(msg)) = failed.
    last_error: Option<Option<String>>,
}

impl Shared {
    fn env<R>(&self, f: impl FnOnce(&BackendEnv) -> R) -> R {
        let llm = self.llm_key.lock().unwrap().clone();
        let hf = self.hf_token.lock().unwrap().clone();
        let env = BackendEnv {
            token: &self.local_token,
            data_dir: &self.data_dir,
            engines_ready: self.data_dir.join("engine-pack").join("installed.json").is_file(),
            llm_api_key: llm.as_deref(),
            hf_token: hf.as_deref(),
            bundled: self.bundled.as_deref(),
        };
        f(&env)
    }

    fn make_backend(&self, s: &Settings) -> Option<Arc<LocalBackend>> {
        self.env(|e| s.local_backend(e))
    }

    fn engine_tool(&self, s: &Settings) -> EngineTool {
        self.env(|e| s.engine_tool(e))
    }

    /// The credential for whichever server is selected.
    fn credential(&self, s: &Settings) -> Option<String> {
        if s.mode == "local" {
            Some(self.local_token.clone())
        } else {
            self.user_token.lock().unwrap().clone()
        }
    }
}

/// The login token in the operating system's credential store (Windows Credential Manager, ...).
/// If the store is unavailable the token simply is not remembered: the user signs in again next launch.
struct KeyringStore {
    user: &'static str,
}

impl KeyringStore {
    fn entry(&self) -> Result<keyring::Entry, String> {
        keyring::Entry::new("id.rekamind.desktop", self.user).map_err(|e| e.to_string())
    }
}

impl TokenStore for KeyringStore {
    fn load(&self) -> Option<String> {
        self.entry().ok()?.get_password().ok()
    }
    fn save(&self, token: &str) -> Result<(), String> {
        self.entry()?.set_password(token).map_err(|e| e.to_string())
    }
    fn clear(&self) {
        if let Ok(e) = self.entry() {
            let _ = e.delete_credential();
        }
    }
}

fn backend_factory() -> Box<dyn Backend> {
    // Developer / CI aid: tones instead of real devices, so the whole shell can be exercised
    // on a machine with no microphone.
    if std::env::var("REKAMIND_SYNTHETIC").is_ok() {
        let s = Script { realtime: true, active_ms: u64::MAX / 4, ..Script::default() };
        return Box::new(SyntheticBackend::new(Script { hz: 440.0, ..s.clone() }, Script { hz: 660.0, ..s }));
    }
    default_backend()
}

/// Show the window, creating it if it does not exist. The window is destroyed when closed (see
/// `run`), because the WebView is by far the heaviest part of the app: with it gone, a recording in
/// progress costs only the small Rust process.
fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
        return;
    }
    let recording = app.state::<Shared>().ctl.is_recording();
    let built = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title(if recording { "● Merekam: Rekamind" } else { "Rekamind" })
        .inner_size(1100.0, 780.0)
        .min_inner_size(420.0, 560.0)
        .build();
    if let Err(e) = built {
        eprintln!("gagal membuka jendela: {e}");
    }
}

fn clock(secs: f64) -> String {
    let s = secs as u64;
    format!("{:02}:{:02}:{:02}", s / 3600, s % 3600 / 60, s % 60)
}

/// Make the tray, window title and menu say what is true right now. A visible "recording"
/// indicator is a deliberate part of the design: nobody should be recorded without being able to see it.
fn refresh_chrome(app: &AppHandle, st: &UiState) {
    let sh = app.state::<Shared>();
    let recording = st.phase == Phase::Recording;
    if let Some(tray) = app.tray_by_id("main") {
        let icon = if recording { TRAY_RECORDING } else { TRAY_IDLE };
        if let Ok(img) = Image::from_bytes(icon) {
            let _ = tray.set_icon(Some(img));
        }
        let tip = match st.phase {
            Phase::Recording => format!("Rekamind: merekam {}", clock(st.elapsed_secs)),
            Phase::Uploading => "Rekamind: mengunggah rekaman".to_string(),
            _ => "Rekamind".to_string(),
        };
        let _ = tray.set_tooltip(Some(tip));
    }
    if let Some(item) = sh.toggle_item.lock().unwrap().as_ref() {
        let _ = item.set_text(if recording { "Hentikan rekaman" } else { "Mulai merekam" });
    }
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.set_title(if recording { "● Merekam: Rekamind" } else { "Rekamind" });
    }
}

fn notify(app: &AppHandle, title: &str, body: &str) {
    let _ = app.notification().builder().title(title).body(body).show();
}

/// Called by the controller on every phase change (never per progress tick).
fn on_change(app: &AppHandle) {
    let sh = app.state::<Shared>();
    let st = sh.ctl.state();
    refresh_chrome(app, &st);
    let _ = app.emit("recorder://changed", ());
    let mut last = sh.last_phase.lock().unwrap();
    if *last != st.phase {
        match (&*last, &st.phase) {
            (_, Phase::Recording) => notify(app, "Rekaman dimulai", "Mikrofon dan audio komputer sedang direkam."),
            (Phase::Uploading, Phase::Done) => notify(app, "Rapat terunggah", "Transkrip dan task akan tersedia setelah diproses."),
            (_, Phase::NeedsAttention) => notify(app, "Rekaman tersimpan, belum terunggah", "Buka Rekamind untuk mencoba lagi."),
            _ => {}
        }
        *last = st.phase.clone();
    }
}

fn toggle_recording(app: &AppHandle) {
    let (sh, app) = (app.state::<Shared>().ctl.clone(), app.clone());
    // Opening a device can take a moment: never on the thread that handles the tray/hotkey event.
    std::thread::spawn(move || {
        let result = if sh.is_recording() { sh.stop() } else { sh.start("") };
        if let Err(e) = result {
            notify(&app, "Rekamind", &e);
        }
    });
}

fn register_hotkey(app: &AppHandle, hotkey: &str) {
    let sh = app.state::<Shared>();
    let gs = app.global_shortcut();
    let _ = gs.unregister_all();
    let err = gs.register(hotkey).err().map(|e| format!("Pintasan {hotkey} tidak bisa dipakai (mungkin dipakai aplikasi lain): {e}"));
    *sh.hotkey_error.lock().unwrap() = err;
}

/// One watcher for the app's lifetime. It asks the controller for the *current* backend each tick (the
/// backend object is replaced when settings or engines change) and does not shut anything down while the
/// window is open: the UI polls and would only start it again.
fn start_watcher(app: &AppHandle) {
    let sh = app.state::<Shared>();
    let (cur, win) = (app.clone(), app.clone());
    let w = Watcher::start_dynamic(
        move || cur.state::<Shared>().ctl.local_backend(),
        move || win.get_webview_window("main").is_some(),
        BACKEND_IDLE_AFTER,
        Duration::from_secs(60),
    );
    *sh.watcher.lock().unwrap() = Some(w);
}

// ----------------------------------------------------------------------------- commands

#[tauri::command]
fn recorder_state(sh: State<'_, Shared>) -> UiState {
    sh.ctl.state()
}

#[tauri::command]
async fn recorder_start(sh: State<'_, Shared>, title: String) -> Result<(), String> {
    let ctl = sh.ctl.clone();
    tauri::async_runtime::spawn_blocking(move || ctl.start(&title)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn recorder_stop(sh: State<'_, Shared>) -> Result<(), String> {
    let ctl = sh.ctl.clone();
    tauri::async_runtime::spawn_blocking(move || ctl.stop()).await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn recorder_retry(sh: State<'_, Shared>, dir: String) -> Result<(), String> {
    sh.ctl.retry_upload(std::path::Path::new(&dir))
}

#[tauri::command]
fn recorder_discard(app: AppHandle, sh: State<'_, Shared>, dir: String) -> Result<(), String> {
    sh.ctl.discard(std::path::Path::new(&dir))?;
    on_change(&app);
    Ok(())
}

#[tauri::command]
fn recorder_dismiss(app: AppHandle, sh: State<'_, Shared>) {
    sh.ctl.clear_last();
    on_change(&app);
}

#[derive(serde::Serialize)]
struct SettingsView {
    settings: Settings,
    server_url: String,
    /// Credential the UI must send to the selected server (the local secret, or the signed-in token).
    auth_token: Option<String>,
    recordings_dir: String,
    hotkey_error: Option<String>,
    /// Secrets are never sent to the UI, only whether they are set.
    has_llm_key: bool,
    has_hf_token: bool,
    /// True when this build carries its own backend (the installer); false in a development checkout.
    bundled_backend: bool,
    backend_dir: String,
}

fn view(sh: &Shared) -> SettingsView {
    let s = sh.settings.lock().unwrap().clone();
    SettingsView { server_url: s.server_url(), auth_token: sh.credential(&s), settings: s, recordings_dir: sh.recordings.to_string_lossy().into_owned(), hotkey_error: sh.hotkey_error.lock().unwrap().clone(), has_llm_key: sh.llm_key.lock().unwrap().is_some(), has_hf_token: sh.hf_token.lock().unwrap().is_some(), bundled_backend: sh.bundled.is_some(), backend_dir: sh.data_dir.to_string_lossy().into_owned() }
}

#[tauri::command]
fn settings_get(sh: State<'_, Shared>) -> SettingsView {
    view(&sh)
}

#[tauri::command]
fn settings_set(app: AppHandle, sh: State<'_, Shared>, settings: Settings) -> Result<SettingsView, String> {
    if sh.ctl.is_recording() {
        return Err("Hentikan rekaman dulu sebelum mengubah pengaturan.".into());
    }
    let settings = settings.validated()?;
    settings.save(&sh.settings_path).map_err(|e| format!("tidak bisa menyimpan pengaturan: {e}"))?;
    let old_hotkey = sh.settings.lock().unwrap().hotkey.clone();
    // The previous local backend (if we started one) is ours to stop before replacing it.
    if let Some(old) = sh.ctl.local_backend() {
        old.stop();
    }
    sh.ctl.set_config(settings.to_config(sh.credential(&settings).as_deref()));
    sh.ctl.set_local_backend(sh.make_backend(&settings));
    *sh.settings.lock().unwrap() = settings.clone();
    if settings.hotkey != old_hotkey {
        register_hotkey(&app, &settings.hotkey);
    }
    Ok(view(&sh))
}

/// The UI needs the backend to show history. In local mode it may not be running (it is started
/// on demand), so the UI asks for it here and shows progress while it comes up.
#[tauri::command]
async fn backend_ensure(sh: State<'_, Shared>) -> Result<(), String> {
    // The backend was stopped on purpose so the engine pack can be replaced; bringing it back now would
    // hold files the installer needs. It is restarted when the job ends.
    if sh.engine_job.lock().unwrap().running.is_some() {
        return Err(ENGINE_BUSY.into());
    }
    let ctl = sh.ctl.clone();
    tauri::async_runtime::spawn_blocking(move || ctl.ensure_backend(Duration::from_secs(90))).await.map_err(|e| e.to_string())?
}

#[derive(serde::Serialize)]
struct LoginResult {
    email: String,
    token: String,
    /// False when the OS credential store refused it: the user is signed in for now, but will have
    /// to sign in again next time the app starts.
    remembered: bool,
}

/// Sign in to a remote server with Google, through the system browser (see `rekamind_recorder::login`).
#[tauri::command]
async fn auth_login(sh: State<'_, Shared>) -> Result<LoginResult, String> {
    let settings = sh.settings.lock().unwrap().clone();
    if settings.mode != "remote" {
        return Err("Mode lokal tidak memerlukan login.".into());
    }
    let server = settings.server_url();
    let store = sh.store.clone();
    let (email, token, remembered) = tauri::async_runtime::spawn_blocking(move || -> Result<(String, String, bool), String> {
        let pending = PendingLogin::begin(&server).map_err(|e| format!("tidak bisa membuka port lokal untuk login: {e}"))?;
        webbrowser::open(&pending.url).map_err(|e| format!("tidak bisa membuka browser ({e}). Buka alamat ini sendiri: {}", pending.url))?;
        let code = pending.wait_for_code(Duration::from_secs(300))?;
        let t = Client::new(&server, None).desktop_token(&code, &pending.verifier).map_err(|e| e.to_string())?;
        let remembered = store.save(&t.access_token).is_ok();
        Ok((t.email, t.access_token, remembered))
    })
    .await
    .map_err(|e| e.to_string())??;
    *sh.user_token.lock().unwrap() = Some(token.clone());
    sh.ctl.set_config(settings.to_config(Some(&token)));
    Ok(LoginResult { email, token, remembered })
}

#[tauri::command]
async fn auth_logout(app: AppHandle, sh: State<'_, Shared>) -> Result<(), String> {
    let settings = sh.settings.lock().unwrap().clone();
    let token = sh.user_token.lock().unwrap().take();
    sh.store.clear();
    sh.ctl.set_config(settings.to_config(sh.credential(&settings).as_deref()));
    if let (Some(t), true) = (token, settings.mode == "remote") {
        let server = settings.server_url();
        // Best effort: even if the server is unreachable the local token is already gone.
        let _ = tauri::async_runtime::spawn_blocking(move || Client::new(&server, Some(t)).logout()).await;
    }
    on_change(&app);
    Ok(())
}

// ----------------------------------------------------------------------------- engines

/// Where the installer put the backend: `<resources>/backend/rekamind-backend[.exe]`. `REKAMIND_BACKEND_BIN`
/// overrides it (used to test a freshly frozen build without installing it).
fn bundled_backend(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(p) = std::env::var("REKAMIND_BACKEND_BIN") {
        let p = PathBuf::from(p);
        return p.is_file().then_some(p);
    }
    let exe = if cfg!(windows) { "rekamind-backend.exe" } else { "rekamind-backend" };
    let p = app.path().resource_dir().ok()?.join("backend").join(exe);
    p.is_file().then_some(p)
}

#[derive(serde::Serialize)]
struct EngineState {
    /// The `status` document from the backend program (pack_dir, asr, diarize, kind).
    pack: serde_json::Value,
    job: EngineJob,
}

#[tauri::command]
async fn engines_status(sh: State<'_, Shared>) -> Result<EngineState, String> {
    let tool = sh.engine_tool(&sh.settings.lock().unwrap().clone());
    let pack = tauri::async_runtime::spawn_blocking(move || tool.status()).await.map_err(|e| e.to_string())??;
    Ok(EngineState { pack, job: sh.engine_job.lock().unwrap().clone() })
}

/// Really imports the engines and reports GPU visibility; run after an install and from "Uji mesin".
#[tauri::command]
async fn engines_check(sh: State<'_, Shared>) -> Result<serde_json::Value, String> {
    let tool = sh.engine_tool(&sh.settings.lock().unwrap().clone());
    tauri::async_runtime::spawn_blocking(move || tool.check()).await.map_err(|e| e.to_string())?
}

fn start_engine_job(app: AppHandle, label: String, args: Vec<String>) -> Result<(), String> {
    // An install that includes speaker separation, when it succeeds, also turns it on (see below).
    let installs_diarizer = label.starts_with("install") && args.iter().any(|a| a == "--diarize");
    let sh = app.state::<Shared>();
    if sh.ctl.is_recording() {
        return Err("Selesaikan rekaman dulu: pemasangan memakai banyak CPU dan jaringan.".into());
    }
    {
        let mut job = sh.engine_job.lock().unwrap();
        if job.running.is_some() {
            return Err("Masih ada pemasangan yang berjalan.".into());
        }
        *job = EngineJob { running: Some(label), log: VecDeque::new(), last_error: None };
    }
    sh.engine_cancel.store(false, Ordering::SeqCst);
    // The backend must not hold files of the pack while it is being replaced.
    if let Some(lb) = sh.ctl.local_backend() {
        lb.stop();
    }
    let settings = sh.settings.lock().unwrap().clone();
    let tool = sh.engine_tool(&settings);
    std::thread::spawn(move || {
        let sh = app.state::<Shared>();
        let argv: Vec<&str> = args.iter().map(String::as_str).collect();
        let res = tool.run_streaming(&argv, &sh.engine_cancel, &mut |line| {
            let mut job = sh.engine_job.lock().unwrap();
            job.log.push_back(line.to_string());
            while job.log.len() > 300 {
                job.log.pop_front();
            }
            drop(job);
            let _ = app.emit("engines://line", line);
        });
        {
            let mut job = sh.engine_job.lock().unwrap();
            job.running = None;
            job.last_error = Some(res.as_ref().err().cloned());
        }
        // Speaker separation was installed on purpose: use it, without a hidden second step in Settings.
        if res.is_ok() && installs_diarizer {
            let mut cur = sh.settings.lock().unwrap();
            if cur.enable_diarizer_after_install() {
                let _ = cur.save(&sh.settings_path);
            }
        }
        // A finished install changes what the backend may do (REKAMIND_ENGINES), so rebuild it.
        let current = sh.settings.lock().unwrap().clone();
        sh.ctl.set_local_backend(sh.make_backend(&current));
        let _ = app.emit("engines://done", res.err());
    });
    Ok(())
}

#[tauri::command]
fn engines_install(app: AppHandle, kind: String, diarize: bool) -> Result<(), String> {
    if !["cpu", "cuda", "openvino", "vulkan"].contains(&kind.as_str()) {
        return Err("Jenis pemasangan harus cpu, cuda, openvino, atau vulkan.".into());
    }
    let mut args = vec!["install".to_string(), kind.clone()];
    if diarize {
        args.push("--diarize".into());
    }
    start_engine_job(app, format!("install {kind}"), args)
}

/// Download the Whisper weights now instead of at the first meeting.
#[tauri::command]
fn engines_warmup(app: AppHandle) -> Result<(), String> {
    let model = app.state::<Shared>().settings.lock().unwrap().whisper_model.clone();
    start_engine_job(app, "warmup".into(), vec!["warmup".into(), model])
}

#[tauri::command]
fn engines_cancel(sh: State<'_, Shared>) {
    sh.engine_cancel.store(true, Ordering::SeqCst);
}

// ----------------------------------------------------------------------------- updates

/// Is a newer release out? Asked by the UI shortly after start and every few hours.
#[tauri::command]
async fn update_check() -> Result<Option<Update>, String> {
    tauri::async_runtime::spawn_blocking(|| update::check(env!("CARGO_PKG_VERSION")))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}

/// Download the newer installer (verified against the release's SHA-256), run it and quit so it can
/// replace the files. Refused while a recording, an upload or an engine install is in progress.
#[tauri::command]
async fn update_install(app: AppHandle, sh: State<'_, Shared>) -> Result<(), String> {
    if matches!(sh.ctl.state().phase, Phase::Recording | Phase::Uploading) || sh.engine_job.lock().unwrap().running.is_some() {
        return Err("Selesaikan rekaman, unggahan, atau pemasangan mesin yang sedang berjalan dulu, lalu perbarui.".into());
    }
    let u = tauri::async_runtime::spawn_blocking(|| update::check(env!("CARGO_PKG_VERSION")))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?
        .ok_or("Sudah memakai versi terbaru.")?;
    if u.installer_url.is_none() {
        // No self-installing asset on this platform: the release page is the update.
        return webbrowser::open(&u.html_url).map(|_| ()).map_err(|e| format!("tidak bisa membuka browser ({e}). Buka alamat ini sendiri: {}", u.html_url));
    }
    let dest = std::env::temp_dir().join(format!("Rekamind-{}-setup.exe", u.version));
    let (job, path) = (u.clone(), dest.clone());
    tauri::async_runtime::spawn_blocking(move || update::download(&job, &path))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    // /P: progress only, no questions; /R: start Rekamind again when done (flags of the Tauri NSIS installer).
    std::process::Command::new(&dest)
        .args(["/P", "/R", "/UPDATE"])
        .spawn()
        .map_err(|e| format!("tidak bisa menjalankan pemasang: {e}"))?;
    app.exit(0);
    Ok(())
}

// ----------------------------------------------------------------------------- links

/// The pages the About card links to. A click inside the app would replace the app with that site, so the UI asks the
/// shell to open them in the system browser; the shell opens only these, whatever the UI asks for.
const EXTERNAL_PAGES: [&str; 4] = [
    "https://github.com/handokoaji",
    "https://github.com/sponsors/handokoaji",
    "https://saweria.co/handokoaji",
    "https://www.instagram.com/rhandokoaji",
];

/// `https://github.com/handokoaji` and anything below it, but not `https://github.com/handokoaji.evil.example`.
fn external_allowed(url: &str) -> bool {
    EXTERNAL_PAGES.iter().any(|page| {
        url == *page || url.strip_prefix(page).is_some_and(|rest| rest.starts_with('/'))
    })
}

#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    if !external_allowed(&url) {
        return Err("Alamat ini tidak boleh dibuka dari aplikasi.".into());
    }
    webbrowser::open(&url).map(|_| ()).map_err(|e| format!("tidak bisa membuka browser ({e})"))
}

#[cfg(test)]
mod tests {
    use super::external_allowed;

    #[test]
    fn opens_the_authors_pages_and_what_lies_below_them() {
        for ok in [
            "https://github.com/handokoaji",
            "https://github.com/handokoaji/rekamind",
            "https://github.com/handokoaji/rekamind/issues",
            "https://github.com/sponsors/handokoaji",
            "https://saweria.co/handokoaji",
            "https://www.instagram.com/rhandokoaji/",
        ] {
            assert!(external_allowed(ok), "{ok}");
        }
    }

    #[test]
    fn refuses_look_alikes_other_hosts_and_other_schemes() {
        for bad in [
            "https://github.com/handokoaji.evil.example",
            "https://github.com/handokoaji@evil.example",
            "https://github.com.evil.example/handokoaji",
            "https://github.com/someone-else",
            "http://github.com/handokoaji",
            "file:///C:/Windows/System32/calc.exe",
            "javascript:alert(1)",
            "",
        ] {
            assert!(!external_allowed(bad), "{bad}");
        }
    }
}

/// `None` leaves a secret as it is; an empty string removes it.
#[tauri::command]
fn secrets_set(sh: State<'_, Shared>, llm_api_key: Option<String>, hf_token: Option<String>) -> Result<SettingsView, String> {
    if sh.ctl.is_recording() {
        return Err("Hentikan rekaman dulu sebelum mengubah pengaturan.".into());
    }
    for (value, user, slot) in [(llm_api_key, "llm-api-key", &sh.llm_key), (hf_token, "hf-token", &sh.hf_token)] {
        let Some(v) = value else { continue };
        let v = v.trim().to_string();
        let store = KeyringStore { user };
        if v.is_empty() {
            store.clear();
            *slot.lock().unwrap() = None;
        } else {
            // Still usable for this run if the OS store refuses it; the UI is told via `has_*` either way.
            let _ = store.save(&v);
            *slot.lock().unwrap() = Some(v);
        }
    }
    if let Some(old) = sh.ctl.local_backend() {
        old.stop();
    }
    let current = sh.settings.lock().unwrap().clone();
    sh.ctl.set_local_backend(sh.make_backend(&current));
    Ok(view(&sh))
}

// ----------------------------------------------------------------------------- app

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        toggle_recording(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            let config_dir = app.path().app_config_dir()?;
            let recordings = app.path().app_local_data_dir()?.join("recordings");
            std::fs::create_dir_all(&recordings)?;
            let settings_path = config_dir.join("settings.json");
            let settings = Settings::load(&settings_path);

            let local_token = new_local_token();
            let store: Arc<dyn TokenStore> = Arc::new(KeyringStore { user: "login-token" });
            let user_token = store.load();
            let credential = if settings.mode == "local" { Some(local_token.clone()) } else { user_token.clone() };
            let ctl = Arc::new(Controller::new(recordings.clone(), settings.to_config(credential.as_deref()), backend_factory));
            let handle = app.handle().clone();
            ctl.set_observer(move || on_change(&handle));

            // Logout / `kill` / Ctrl+C: finish the recording properly instead of leaving a crashed one.
            let h = app.handle().clone();
            let _ = ctrlc::set_handler(move || {
                let sh = h.state::<Shared>();
                sh.ctl.stop_for_quit();
                if let Some(lb) = sh.ctl.local_backend() {
                    lb.stop();
                }
                h.exit(0);
            });

            let hotkey = settings.hotkey.clone();
            let data_dir = app.path().app_local_data_dir()?.join("backend");
            std::fs::create_dir_all(&data_dir)?;
            let bundled = bundled_backend(app.handle());
            app.manage(Shared {
                ctl,
                settings: Mutex::new(settings),
                settings_path,
                recordings,
                toggle_item: Mutex::new(None),
                tray_ok: Mutex::new(false),
                last_phase: Mutex::new(Phase::Idle),
                watcher: Mutex::new(None),
                hotkey_error: Mutex::new(None),
                local_token,
                store,
                user_token: Mutex::new(user_token),
                data_dir,
                bundled,
                llm_key: Mutex::new(KeyringStore { user: "llm-api-key" }.load()),
                hf_token: Mutex::new(KeyringStore { user: "hf-token" }.load()),
                engine_job: Mutex::new(EngineJob::default()),
                engine_cancel: AtomicBool::new(false),
            });
            let sh = app.state::<Shared>();
            let current = sh.settings.lock().unwrap().clone();
            sh.ctl.set_local_backend(sh.make_backend(&current));
            start_watcher(app.handle());
            register_hotkey(app.handle(), &hotkey);

            // The tray is a convenience, not a requirement: if the desktop has none, carry on without it.
            let built = (|| -> tauri::Result<()> {
                let toggle = MenuItem::with_id(app, "toggle", "Mulai merekam", true, None::<&str>)?;
                let open = MenuItem::with_id(app, "open", "Buka Rekamind", true, None::<&str>)?;
                let quit = MenuItem::with_id(app, "quit", "Keluar", true, None::<&str>)?;
                let menu = Menu::with_items(app, &[&toggle, &open, &PredefinedMenuItem::separator(app)?, &quit])?;
                TrayIconBuilder::with_id("main")
                    .icon(Image::from_bytes(TRAY_IDLE)?)
                    .tooltip("Rekamind")
                    .menu(&menu)
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| match event.id.as_ref() {
                        "toggle" => toggle_recording(app),
                        "open" => show_main(app),
                        "quit" => {
                            let sh = app.state::<Shared>();
                            sh.ctl.stop_for_quit();
                            if let Some(lb) = sh.ctl.local_backend() {
                                lb.stop();
                            }
                            app.exit(0);
                        }
                        _ => {}
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                            show_main(tray.app_handle());
                        }
                    })
                    .build(app)?;
                *app.state::<Shared>().toggle_item.lock().unwrap() = Some(toggle);
                Ok(())
            })();
            let built_ok = built.is_ok();
            *app.state::<Shared>().tray_ok.lock().unwrap() = built_ok;
            if let Err(e) = built {
                eprintln!("tray tidak tersedia, lanjut tanpa tray: {e}");
            }

            // Started minimised to the tray (e.g. at login): no window, no WebView, nothing heavy.
            // Without a tray there would be no way back, so then the window opens regardless.
            let hidden = std::env::args().any(|a| a == "--hidden");
            if !(hidden && built_ok) {
                show_main(app.handle());
            }

            // While recording, keep the tooltip's clock fresh. Wakes every 15 s only to do that.
            let h = app.handle().clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(Duration::from_secs(15));
                let st = h.state::<Shared>().ctl.state();
                if st.phase == Phase::Recording {
                    refresh_chrome(&h, &st);
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            recorder_state,
            recorder_start,
            recorder_stop,
            recorder_retry,
            recorder_discard,
            recorder_dismiss,
            settings_get,
            settings_set,
            backend_ensure,
            auth_login,
            auth_logout,
            engines_status,
            engines_check,
            engines_install,
            engines_warmup,
            engines_cancel,
            secrets_set,
            update_check,
            update_install,
            open_external,
        ])
        .build(tauri::generate_context!())
        .expect("gagal membangun aplikasi Rekamind");

    app.run(|app, event| match event {
        RunEvent::ExitRequested { code, api, .. } => {
            let sh = app.state::<Shared>();
            // Closing the last window must not quit while a tray icon exists: the recorder and the
            // tray keep running. Only an explicit exit (tray "Keluar", SIGTERM, logout) quits.
            if code.is_none() && *sh.tray_ok.lock().unwrap() {
                api.prevent_exit();
                return;
            }
            sh.ctl.stop_for_quit();
            if let Some(lb) = sh.ctl.local_backend() {
                lb.stop();
            }
        }
        RunEvent::Exit => {
            // Last line of defence: whatever the reason for exiting, close the WAV files properly.
            let sh = app.state::<Shared>();
            sh.ctl.stop_for_quit();
            if let Some(lb) = sh.ctl.local_backend() {
                lb.stop();
            }
        }
        _ => {}
    });
}
