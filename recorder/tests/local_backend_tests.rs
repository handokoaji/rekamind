#![cfg(unix)]
mod common;
use rekamind_recorder::backend::synthetic::{Script, SyntheticBackend};
use rekamind_recorder::controller::{Config, Controller, Phase};
use rekamind_recorder::local_backend::LocalBackend;
use std::sync::Arc;
use std::time::{Duration, Instant};

/// A real child process standing in for `python -m rekamind_server`: serves /api/health and
/// /api/meetings (busy while a `busy` file exists) and the upload endpoints.
fn fake_server_script(dir: &std::path::Path, port: u16) -> (String, Vec<String>) {
    let script = dir.join("fake_backend.py");
    std::fs::write(
        &script,
        format!(
            r#"
import json, os, http.server
BUSY = {busy:?}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type","application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/api/health"): self._send(200, {{"status":"ok"}})
        elif self.path.startswith("/api/meetings") and os.environ.get("FAKE_TOKEN") and self.headers.get("Authorization") != "Bearer " + os.environ["FAKE_TOKEN"]: self._send(401, {{"detail":"Silakan masuk."}})
        elif self.path.startswith("/api/meetings"): self._send(200, [{{"id":"m1","job": {{"status":"running"}} if os.path.exists(BUSY) else None}}])
        else: self._send(404, {{"detail":"x"}})
    def _drain(self):
        n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
    def do_POST(self):
        self._drain()
        self._send(201 if self.path == "/api/meetings" else 200, {{"id":"abc123"}})
    def do_PUT(self):
        self._drain(); self._send(201, {{"bytes": 1}})
http.server.ThreadingHTTPServer(("127.0.0.1", {port}), H).serve_forever()
"#,
            busy = dir.join("busy").to_string_lossy().to_string(),
            port = port
        ),
    )
    .unwrap();
    (
        "python3".into(),
        vec![script.to_string_lossy().into_owned()],
    )
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

#[test]
fn starts_on_demand_reports_ready_and_stops_cleanly() {
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let lb = LocalBackend::new(prog, args, vec![], format!("http://127.0.0.1:{port}"));
    assert!(!lb.is_healthy(), "nothing is running before we ask");
    lb.ensure(Duration::from_secs(10)).unwrap();
    assert!(lb.is_healthy() && lb.owns_process());
    lb.stop();
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        !lb.is_healthy(),
        "stop really ends the process (frees RAM/GPU)"
    );
}

#[test]
fn a_backend_that_is_already_running_is_used_but_never_killed() {
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let mut other = std::process::Command::new(&prog)
        .args(&args)
        .spawn()
        .unwrap(); // somebody else's backend
    std::thread::sleep(Duration::from_millis(800));
    let lb = LocalBackend::new(prog, args, vec![], format!("http://127.0.0.1:{port}"));
    lb.ensure(Duration::from_secs(5)).unwrap();
    assert!(!lb.owns_process());
    assert!(!lb.idle_tick(Duration::ZERO), "not ours, so never stopped");
    assert!(lb.is_healthy());
    let _ = other.kill();
    let _ = other.wait();
}

#[test]
fn it_is_stopped_only_after_the_queue_has_been_empty_for_the_idle_period() {
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let lb = LocalBackend::new(prog, args, vec![], format!("http://127.0.0.1:{port}"));
    lb.ensure(Duration::from_secs(10)).unwrap();

    std::fs::write(d.path().join("busy"), "").unwrap(); // a job is running
    assert!(
        !lb.idle_tick(Duration::ZERO),
        "a busy backend is never stopped, even with zero patience"
    );
    assert!(lb.owns_process());

    std::fs::remove_file(d.path().join("busy")).unwrap();
    assert!(
        !lb.idle_tick(Duration::from_millis(400)),
        "idle clock only just started"
    );
    std::thread::sleep(Duration::from_millis(500));
    assert!(
        lb.idle_tick(Duration::from_millis(400)),
        "idle long enough -> stopped"
    );
    assert!(!lb.owns_process());
}

#[test]
fn a_backend_that_dies_on_startup_gives_a_clear_error_quickly() {
    let lb = LocalBackend::new(
        "sh",
        vec!["-c".into(), "exit 3".into()],
        vec![],
        "http://127.0.0.1:1",
    );
    let t = Instant::now();
    let e = lb.ensure(Duration::from_secs(30)).unwrap_err();
    assert!(e.contains("berhenti saat dinyalakan"), "{e}");
    assert!(
        t.elapsed() < Duration::from_secs(5),
        "did not wait out the whole timeout"
    );
}

#[test]
fn a_missing_program_says_which_one() {
    let lb = LocalBackend::new("/no/such/python", vec![], vec![], "http://127.0.0.1:1");
    assert!(lb
        .ensure(Duration::from_secs(1))
        .unwrap_err()
        .contains("/no/such/python"));
}

#[test]
fn a_backend_that_never_becomes_ready_is_stopped_and_reported() {
    let lb = LocalBackend::new("sleep", vec!["30".into()], vec![], "http://127.0.0.1:1");
    let e = lb.ensure(Duration::from_secs(1)).unwrap_err();
    assert!(e.contains("tidak siap"), "{e}");
    assert!(!lb.owns_process(), "no zombie left running");
}

#[test]
fn recording_then_stopping_starts_the_local_backend_uploads_and_it_idles_out() {
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let url = format!("http://127.0.0.1:{port}");
    let lb = Arc::new(LocalBackend::new(prog, args, vec![], url.clone()));
    assert!(
        !lb.is_healthy(),
        "the backend is NOT running while the meeting is recorded"
    );

    let synth = || -> Box<dyn rekamind_recorder::backend::Backend> {
        let s = Script {
            realtime: true,
            active_ms: 60_000,
            ..Default::default()
        };
        Box::new(SyntheticBackend::new(s.clone(), s))
    };
    let root = d.path().join("rec");
    let c = Controller::new(
        root,
        Config {
            server: Some(url),
            ..Default::default()
        },
        synth,
    )
    .with_local_backend(lb.clone());
    c.start("Rapat lokal").unwrap();
    std::thread::sleep(Duration::from_millis(600));
    assert!(
        !lb.is_healthy(),
        "still off during recording: that is the whole point"
    );
    c.stop().unwrap();

    let t = Instant::now();
    loop {
        let s = c.state();
        if s.phase == Phase::Done {
            assert_eq!(s.last.unwrap().meeting_id.as_deref(), Some("abc123"));
            break;
        }
        assert!(s.phase != Phase::NeedsAttention, "{:?}", s.last);
        assert!(t.elapsed() < Duration::from_secs(20), "timed out: {s:?}");
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(
        lb.owns_process(),
        "started on demand after the meeting ended"
    );
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        lb.idle_tick(Duration::from_millis(100)) || {
            std::thread::sleep(Duration::from_millis(200));
            lb.idle_tick(Duration::from_millis(100))
        }
    );
    assert!(!lb.owns_process(), "and shut down again once idle");
}

#[test]
fn nothing_can_bring_the_backend_back_while_a_recording_is_running() {
    // Regression found by running the real app: the UI's status poll raced with the start of a
    // recording, saw the backend (just stopped) as down, and asked for it again -> it respawned
    // mid-meeting. The controller itself must refuse.
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let lb = Arc::new(LocalBackend::new(
        prog,
        args,
        vec![],
        format!("http://127.0.0.1:{port}"),
    ));
    let synth = || -> Box<dyn rekamind_recorder::backend::Backend> {
        let s = Script {
            realtime: true,
            active_ms: 60_000,
            ..Default::default()
        };
        Box::new(SyntheticBackend::new(s.clone(), s))
    };
    let c = Controller::new(d.path().join("rec"), Config::default(), synth)
        .with_local_backend(lb.clone());

    c.ensure_backend(Duration::from_secs(10)).unwrap(); // fine while idle
    assert!(lb.owns_process() && lb.is_healthy());

    c.start("Rapat").unwrap();
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        !lb.owns_process(),
        "starting a recording stopped the idle backend"
    );
    for _ in 0..3 {
        let e = c.ensure_backend(Duration::from_secs(5)).unwrap_err();
        assert!(e.contains("selama merekam"), "{e}");
    }
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        !lb.owns_process() && !lb.is_healthy(),
        "no backend process exists during the meeting"
    );

    c.stop().unwrap();
    c.ensure_backend(Duration::from_secs(10)).unwrap(); // and it comes back afterwards
    assert!(lb.is_healthy());
    lb.stop();
}

#[test]
fn recording_a_second_meeting_straight_away_holds_the_first_upload_until_it_ends() {
    // The first meeting's upload wants the local backend; the user starts the next meeting at once.
    // Heavy work must wait for the second meeting to finish, then both uploads must complete.
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let url = format!("http://127.0.0.1:{port}");
    let lb = Arc::new(LocalBackend::new(prog, args, vec![], url.clone()));
    let synth = || -> Box<dyn rekamind_recorder::backend::Backend> {
        let s = Script {
            realtime: true,
            active_ms: 60_000,
            ..Default::default()
        };
        Box::new(SyntheticBackend::new(s.clone(), s))
    };
    let c = Controller::new(
        d.path().join("rec"),
        Config {
            server: Some(url),
            ..Default::default()
        },
        synth,
    )
    .with_local_backend(lb.clone());

    c.start("Rapat A").unwrap();
    std::thread::sleep(Duration::from_millis(1100)); // distinct folder names (second resolution)
    c.stop().unwrap(); // upload A begins: wants the backend
    c.start("Rapat B").unwrap(); // ...but a new meeting starts immediately
    for _ in 0..8 {
        std::thread::sleep(Duration::from_millis(400));
        assert!(
            !lb.is_healthy(),
            "a backend process came up during meeting B"
        );
        let s = c.state();
        assert_eq!(s.phase, Phase::Recording);
    }
    std::thread::sleep(Duration::from_millis(500));
    c.stop().unwrap(); // meeting B ends: now both can upload

    let t = Instant::now();
    loop {
        let s = c.state();
        if s.phase == Phase::Done && s.upload.is_none() && s.pending.is_empty() {
            break;
        }
        assert!(s.phase != Phase::NeedsAttention, "{:?}", s.last);
        assert!(t.elapsed() < Duration::from_secs(40), "timed out: {s:?}");
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        c.scan_pending().is_empty(),
        "both meetings reached the server"
    );
    lb.stop();
}

#[test]
fn idle_shutdown_authenticates_with_the_local_secret() {
    // Regression found by running the real shell: the idle watcher asked "anything running?"
    // without the secret, got 401, treated that as "cannot tell" and never stopped the backend.
    let d = tempfile::tempdir().unwrap();
    let port = free_port();
    let (prog, args) = fake_server_script(d.path(), port);
    let url = format!("http://127.0.0.1:{port}");
    let env = vec![("FAKE_TOKEN".to_string(), "s3cret".to_string())];

    let anon = LocalBackend::new(prog.clone(), args.clone(), env.clone(), url.clone());
    anon.ensure(Duration::from_secs(10)).unwrap();
    assert!(
        !anon.idle_tick(Duration::ZERO),
        "without the secret it cannot tell, so it must not kill"
    );
    assert!(anon.owns_process());
    anon.stop();

    let lb = LocalBackend::new(prog, args, env, url).with_token("s3cret");
    lb.ensure(Duration::from_secs(10)).unwrap();
    assert!(
        lb.idle_tick(Duration::ZERO),
        "with the secret it sees nothing is queued and stops"
    );
    assert!(!lb.owns_process());
}
