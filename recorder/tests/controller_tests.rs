mod common;
mod mock_server;
use mock_server::{backend_ok, start, Req};
use rekamind_recorder::backend::synthetic::{Script, SyntheticBackend};
use rekamind_recorder::controller::{Config, Controller, Phase, UiState};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

fn synth() -> Box<dyn rekamind_recorder::backend::Backend> {
    let s = Script {
        realtime: true,
        active_ms: 600_000,
        ..Default::default()
    };
    Box::new(SyntheticBackend::new(s.clone(), Script { hz: 660.0, ..s }))
}

fn ctl(root: &std::path::Path, server: Option<&str>) -> Controller {
    let cfg = Config {
        server: server.map(str::to_owned),
        local_user_name: Some("Andi".into()),
        ..Default::default()
    };
    Controller::new(root.to_path_buf(), cfg, synth).with_sleeper(|_| {})
}

fn wait_for(c: &Controller, what: &str, f: impl Fn(&UiState) -> bool) -> UiState {
    let t = Instant::now();
    loop {
        let s = c.state();
        if f(&s) {
            return s;
        }
        assert!(
            t.elapsed() < Duration::from_secs(10),
            "timed out waiting for {what}; state: {s:?}"
        );
        std::thread::sleep(Duration::from_millis(30));
    }
}

fn record_a_bit(c: &Controller, title: &str) {
    c.start(title).unwrap();
    std::thread::sleep(Duration::from_millis(700));
    c.stop().unwrap();
}

#[test]
fn state_while_recording_has_levels_and_a_second_start_is_refused() {
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), None);
    assert_eq!(c.state().phase, Phase::Idle);
    c.start("Rapat vendor").unwrap();
    std::thread::sleep(Duration::from_millis(300));
    let s = c.state();
    assert_eq!(
        (s.phase.clone(), s.title.as_deref()),
        (Phase::Recording, Some("Rapat vendor"))
    );
    assert_eq!(s.sources.len(), 2);
    assert!(
        s.sources
            .iter()
            .all(|x| x.state == "recording" && x.level > 0.05 && x.seconds > 0.1),
        "{:?}",
        s.sources
    );
    assert!(c.start("lagi").unwrap_err().contains("sedang berjalan"));
    c.stop().unwrap();
    assert!(c.stop().is_err(), "stopping twice is an error, not a crash");
}

#[test]
fn stop_uploads_in_the_background_and_ends_done_with_the_meeting_id() {
    let m = start(backend_ok);
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some(&m.url));
    record_a_bit(&c, "Rapat vendor");
    let s = wait_for(&c, "upload to finish", |s| s.phase == Phase::Done);
    assert_eq!(
        s.last.as_ref().unwrap().meeting_id.as_deref(),
        Some("abc123")
    );
    assert!(
        s.pending.is_empty(),
        "an uploaded recording is not 'pending'"
    );
    let seen = m.seen.lock().unwrap();
    let create = seen
        .iter()
        .find(|r| r.method == "POST" && r.path == "/api/meetings")
        .unwrap();
    let body: serde_json::Value = serde_json::from_slice(&create.body).unwrap();
    assert_eq!(
        (body["title"].as_str(), body["local_user_name"].as_str()),
        (Some("Rapat vendor"), Some("Andi"))
    );
    assert!(
        seen.iter()
            .any(|r| r.path == "/api/meetings/abc123/process"),
        "auto_process is on by default"
    );
}

#[test]
fn a_dead_server_never_loses_the_recording_and_retry_works_once_it_is_back() {
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some("http://127.0.0.1:1"));
    record_a_bit(&c, "Rapat penting");
    let s = wait_for(&c, "failure", |s| s.phase == Phase::NeedsAttention);
    assert!(
        s.last
            .as_ref()
            .unwrap()
            .error
            .as_ref()
            .unwrap()
            .contains("aman"),
        "{:?}",
        s.last
    );
    assert_eq!(s.pending.len(), 1);
    assert_eq!(s.pending[0].title, "Rapat penting");
    assert!(!s.pending[0].crashed);

    // The server comes back: point at it and retry the very same folder.
    let m = start(backend_ok);
    c.set_config(Config {
        server: Some(m.url.clone()),
        ..c.config()
    });
    c.retry_upload(std::path::Path::new(&s.pending[0].dir))
        .unwrap();
    let s = wait_for(&c, "retry to succeed", |s| s.phase == Phase::Done);
    assert!(s.pending.is_empty());
    let seen = m.seen.lock().unwrap();
    let create = seen
        .iter()
        .find(|r| r.path == "/api/meetings" && r.method == "POST")
        .unwrap();
    assert!(
        String::from_utf8_lossy(&create.body).contains("Rapat penting"),
        "the saved title survives the retry"
    );
}

#[test]
fn with_no_server_configured_the_recording_is_kept_and_the_user_is_told_why() {
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), None);
    record_a_bit(&c, "Tanpa server");
    let s = wait_for(&c, "attention", |s| s.phase == Phase::NeedsAttention);
    assert!(s.last.unwrap().error.unwrap().contains("belum diatur"));
    assert_eq!(s.pending.len(), 1);
}

#[test]
fn a_crash_mid_recording_is_found_flagged_and_uploaded_with_its_saved_title() {
    let root = tempfile::tempdir().unwrap();
    let c = ctl(root.path(), None);
    c.start("Rapat sebelum mati").unwrap();
    std::thread::sleep(Duration::from_millis(2600)); // past a WAV checkpoint
                                                     // Power cut: snapshot the folder as it is, then let the real session end normally.
    let live = std::fs::read_dir(root.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let crashed = root.path().join("rapat-crashed");
    std::fs::create_dir_all(&crashed).unwrap();
    for e in std::fs::read_dir(&live).unwrap() {
        let e = e.unwrap();
        std::fs::copy(e.path(), crashed.join(e.file_name())).unwrap();
    }
    c.stop().unwrap();

    let pending = c.scan_pending();
    let hit = pending
        .iter()
        .find(|p| p.dir.ends_with("rapat-crashed"))
        .expect("crashed folder is listed");
    assert!(hit.crashed && hit.title == "Rapat sebelum mati", "{hit:?}");

    let m = start(backend_ok);
    c.set_config(Config {
        server: Some(m.url.clone()),
        ..c.config()
    });
    c.retry_upload(&crashed).unwrap();
    wait_for(&c, "recovered upload", |s| s.phase == Phase::Done);
    let seen = m.seen.lock().unwrap();
    let put = seen
        .iter()
        .find(|r| r.method == "PUT" && r.path.ends_with("/mic"))
        .unwrap();
    assert!(
        put.body.len() > 44 + 32_000,
        "repaired audio was uploaded, {} bytes",
        put.body.len()
    );
    assert!(
        !c.scan_pending()
            .iter()
            .any(|p| p.dir.ends_with("rapat-crashed")),
        "no longer pending after upload"
    );
}

#[test]
fn a_flaky_server_gets_retried_per_file_and_the_bytes_still_arrive_intact() {
    let puts = Arc::new(AtomicUsize::new(0));
    let p2 = puts.clone();
    let m = start(move |r: &Req| {
        if r.method == "PUT" && p2.fetch_add(1, Ordering::SeqCst) == 0 {
            return (503, r#"{"detail":"sibuk"}"#.into()); // first upload attempt fails
        }
        backend_ok(r)
    });
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some(&m.url));
    record_a_bit(&c, "Server sibuk");
    wait_for(&c, "success after retry", |s| s.phase == Phase::Done);
    let seen = m.seen.lock().unwrap();
    let puts: Vec<&Req> = seen.iter().filter(|r| r.method == "PUT").collect();
    assert_eq!(
        puts.len(),
        3,
        "mic failed once and was retried, then speaker"
    );
    assert_eq!(puts[0].path, puts[1].path);
    assert_eq!(&puts[1].body[..4], b"RIFF");
}

#[test]
fn auto_process_can_be_turned_off() {
    let m = start(backend_ok);
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some(&m.url));
    c.set_config(Config {
        auto_process: false,
        ..c.config()
    });
    record_a_bit(&c, "Tanpa proses");
    wait_for(&c, "done", |s| s.phase == Phase::Done);
    assert!(!m
        .seen
        .lock()
        .unwrap()
        .iter()
        .any(|r| r.path.ends_with("/process")));
}

#[test]
fn discard_can_only_ever_delete_inside_the_recordings_folder() {
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    std::fs::write(outside.path().join("precious.txt"), "x").unwrap();
    let c = ctl(root.path(), None);
    assert!(c.discard(outside.path()).is_err());
    assert!(c.discard(&root.path().join("..")).is_err());
    assert!(outside.path().join("precious.txt").exists());

    record_a_bit(&c, "Hapus saya");
    let p = c.scan_pending();
    c.discard(std::path::Path::new(&p[0].dir)).unwrap();
    assert!(c.scan_pending().is_empty());
}

#[test]
fn a_recording_in_progress_cannot_be_discarded_or_listed_as_pending() {
    let root = tempfile::tempdir().unwrap();
    let c = ctl(root.path(), None);
    c.start("Sedang jalan").unwrap();
    std::thread::sleep(Duration::from_millis(200));
    assert!(
        c.scan_pending().is_empty(),
        "the live folder is not 'pending'"
    );
    let live = std::fs::read_dir(root.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    assert!(c.discard(&live).unwrap_err().contains("sedang berjalan"));
    c.stop().unwrap();
}

#[test]
fn quitting_while_recording_closes_the_files_properly() {
    let root = tempfile::tempdir().unwrap();
    let c = ctl(root.path(), None);
    c.start("Keluar").unwrap();
    std::thread::sleep(Duration::from_millis(500));
    c.stop_for_quit();
    let dir = std::fs::read_dir(root.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    assert!(
        common::read_wav(&dir.join("mic.wav")).samples.len() > 4000,
        "strictly valid WAV after quit"
    );
    assert!(!c.is_recording());
}

#[test]
fn state_serialises_for_the_ui() {
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), None);
    let json = serde_json::to_value(c.state()).unwrap();
    assert_eq!(json["phase"], "idle");
    c.start("x").unwrap();
    let json = serde_json::to_value(c.state()).unwrap();
    assert_eq!(json["phase"], "recording");
    assert_eq!(json["sources"][0]["source"], "mic");
    assert_eq!(json["sources"][1]["label"], "Audio komputer");
    c.stop().unwrap();
}

#[test]
fn the_observer_hears_about_start_stop_and_the_end_of_the_upload() {
    let m = start(backend_ok);
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some(&m.url));
    let n = Arc::new(AtomicUsize::new(0));
    let n2 = n.clone();
    c.set_observer(move || {
        n2.fetch_add(1, Ordering::SeqCst);
    });
    c.start("x").unwrap();
    assert_eq!(n.load(Ordering::SeqCst), 1, "start");
    std::thread::sleep(Duration::from_millis(300));
    c.stop().unwrap();
    wait_for(&c, "done", |s| s.phase == Phase::Done);
    std::thread::sleep(Duration::from_millis(100));
    assert_eq!(
        n.load(Ordering::SeqCst),
        3,
        "start + stop + upload finished"
    );
}

/// The JSON the desktop UI receives is a contract with web/src/desktop/types.ts. This golden
/// file is read by the web tests too, so a change on either side fails a test instead of the app.
#[test]
fn ui_state_json_matches_the_golden_contract_file() {
    use rekamind_recorder::controller::*;
    let src =
        |s: &'static str, l: &'static str, level: f32, state: &'static str, msg: Option<&str>| {
            SourceView {
                source: s,
                label: l,
                level,
                state,
                message: msg.map(str::to_owned),
                seconds: 12.5,
            }
        };
    let pending = Pending {
        dir: "/rec/rapat-1".into(),
        title: "Rapat vendor".into(),
        created_unix: 1_790_000_000,
        crashed: true,
    };
    let states = serde_json::json!({
        "idle": UiState { phase: Phase::Idle, title: None, elapsed_secs: 0.0, sources: vec![], upload: None, last: None, pending: vec![] },
        "recording": UiState {
            phase: Phase::Recording, title: Some("Rapat vendor".into()), elapsed_secs: 12.5, upload: None, last: None, pending: vec![pending.clone()],
            sources: vec![src("mic", "Mikrofon", 0.4, "recording", None), src("speaker", "Audio komputer", 0.0, "reconnecting", Some("Perangkat terputus, mencoba tersambung lagi…"))],
        },
        "uploading": UiState {
            phase: Phase::Uploading, title: Some("Rapat vendor".into()), elapsed_secs: 0.0, sources: vec![], pending: vec![], last: None,
            upload: Some(UploadView { step: "mengunggah mikrofon".into(), fraction: 0.42 }),
        },
        "done": UiState {
            phase: Phase::Done, title: Some("Rapat vendor".into()), elapsed_secs: 0.0, sources: vec![], upload: None, pending: vec![],
            last: Some(Outcome { title: "Rapat vendor".into(), dir: "/rec/rapat-1".into(), meeting_id: Some("abc123".into()), error: None, warnings: vec![] }),
        },
        "needs_attention": UiState {
            phase: Phase::NeedsAttention, title: Some("Rapat vendor".into()), elapsed_secs: 0.0, sources: vec![], upload: None, pending: vec![pending],
            last: Some(Outcome { title: "Rapat vendor".into(), dir: "/rec/rapat-1".into(), meeting_id: None, error: Some("server tidak terjangkau".into()), warnings: vec!["Mikrofon: tidak ada mikrofon yang aktif".into()] }),
        },
    });
    let path =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../desktop/contract/ui-state.json");
    let pretty = serde_json::to_string_pretty(&states).unwrap() + "\n";
    if std::env::var("UPDATE_CONTRACT").is_ok() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, &pretty).unwrap();
    }
    let on_disk =
        std::fs::read_to_string(&path).expect("contract file missing: run with UPDATE_CONTRACT=1");
    assert_eq!(on_disk, pretty, "UiState JSON changed: update web/src/desktop/types.ts, then regenerate with UPDATE_CONTRACT=1");
}

#[test]
fn an_expired_login_keeps_the_recording_and_says_how_to_continue() {
    let m = start(|r: &Req| {
        if r.path == "/api/health" {
            (200, r#"{"status":"ok"}"#.into())
        } else {
            (401, r#"{"detail":"x"}"#.into())
        }
    });
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some(&m.url));
    record_a_bit(&c, "Sesi habis");
    let s = wait_for(&c, "attention", |s| s.phase == Phase::NeedsAttention);
    let err = s.last.unwrap().error.unwrap();
    assert!(
        err.contains("Sesi login berakhir") && err.contains("aman"),
        "{err}"
    );
    assert_eq!(
        s.pending.len(),
        1,
        "the audio is still on disk, ready to upload after signing in again"
    );
}

#[test]
fn a_refused_process_request_is_a_warning_not_a_failed_upload() {
    // Found by running the installed app on a fresh machine: engines not installed yet -> the server
    // answers 503 to "process", and the UI used to say the recording was NOT uploaded (it was).
    let m = start(|req: &mock_server::Req| {
        if req.path == "/api/meetings/abc123/process" {
            (
                503,
                r#"{"detail":"Mesin pemrosesan belum dikonfigurasi di backend ini"}"#.into(),
            )
        } else {
            backend_ok(req)
        }
    });
    let d = tempfile::tempdir().unwrap();
    let c = ctl(d.path(), Some(&m.url));
    record_a_bit(&c, "Rapat pertama");
    let s = wait_for(&c, "upload to finish", |s| s.phase == Phase::Done);
    let last = s.last.unwrap();
    assert_eq!(last.meeting_id.as_deref(), Some("abc123"));
    assert!(last.error.is_none(), "{:?}", last.error);
    assert!(
        last.warnings
            .iter()
            .any(|w| w.contains("belum diproses") && w.contains("belum dikonfigurasi")),
        "{:?}",
        last.warnings
    );
    assert!(
        s.pending.is_empty(),
        "the recording is uploaded, so it is no longer pending"
    );
}
