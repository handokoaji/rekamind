//! Rekamind desktop shell. All real logic lives in `rekamind-recorder` (tested without a GUI);
//! this file only wires it to the window, tray, global shortcut and notifications.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rekamind_recorder::backend::synthetic::{Script, SyntheticBackend};
use rekamind_recorder::backend::{default_backend, Backend};
use rekamind_recorder::controller::{Controller, Phase, UiState};
use rekamind_recorder::local_backend::Watcher;
use rekamind_recorder::settings::Settings;
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent, Wry};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
use tauri_plugin_notification::NotificationExt;

const TRAY_IDLE: &[u8] = include_bytes!("../icons/tray-idle.png");
const TRAY_RECORDING: &[u8] = include_bytes!("../icons/tray-recording.png");
/// A local backend nobody is using for this long is shut down (frees RAM and the GPU).
const BACKEND_IDLE_AFTER: Duration = Duration::from_secs(10 * 60);

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

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
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

fn restart_watcher(sh: &Shared) {
    let mut w = sh.watcher.lock().unwrap();
    *w = None; // dropping the old one stops its thread
    if let Some(lb) = sh.ctl.local_backend() {
        *w = Some(Watcher::start(lb, BACKEND_IDLE_AFTER, Duration::from_secs(60)));
    }
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
    recordings_dir: String,
    hotkey_error: Option<String>,
}

fn view(sh: &Shared) -> SettingsView {
    let s = sh.settings.lock().unwrap().clone();
    SettingsView { server_url: s.server_url(), settings: s, recordings_dir: sh.recordings.to_string_lossy().into_owned(), hotkey_error: sh.hotkey_error.lock().unwrap().clone() }
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
    sh.ctl.set_config(settings.to_config());
    sh.ctl.set_local_backend(settings.local_backend());
    *sh.settings.lock().unwrap() = settings.clone();
    restart_watcher(&sh);
    if settings.hotkey != old_hotkey {
        register_hotkey(&app, &settings.hotkey);
    }
    Ok(view(&sh))
}

/// The UI needs the backend to show history. In local mode it may not be running (it is started
/// on demand), so the UI asks for it here and shows progress while it comes up.
#[tauri::command]
async fn backend_ensure(sh: State<'_, Shared>) -> Result<(), String> {
    let Some(lb) = sh.ctl.local_backend() else { return Ok(()) };
    tauri::async_runtime::spawn_blocking(move || lb.ensure(Duration::from_secs(90))).await.map_err(|e| e.to_string())?
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
            let recordings = app.path().app_data_dir()?.join("recordings");
            std::fs::create_dir_all(&recordings)?;
            let settings_path = config_dir.join("settings.json");
            let settings = Settings::load(&settings_path);

            let ctl = Arc::new(Controller::new(recordings.clone(), settings.to_config(), backend_factory));
            ctl.set_local_backend(settings.local_backend());
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
            });
            let sh = app.state::<Shared>();
            restart_watcher(&sh);
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
            *app.state::<Shared>().tray_ok.lock().unwrap() = built.is_ok();
            if let Err(e) = built {
                eprintln!("tray tidak tersedia, lanjut tanpa tray: {e}");
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
        .on_window_event(|window, event| {
            // Closing the window must not end a meeting recording: hide to the tray instead.
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let sh = app.state::<Shared>();
                if *sh.tray_ok.lock().unwrap() {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
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
        ])
        .build(tauri::generate_context!())
        .expect("gagal membangun aplikasi Rekamind");

    app.run(|app, event| {
        if let RunEvent::ExitRequested { .. } = event {
            // Whatever the reason for exiting: close the WAV files properly and free the backend.
            let sh = app.state::<Shared>();
            sh.ctl.stop_for_quit();
            if let Some(lb) = sh.ctl.local_backend() {
                lb.stop();
            }
        }
    });
}
