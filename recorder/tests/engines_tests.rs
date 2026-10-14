#![cfg(unix)]
use rekamind_recorder::engines::EngineTool;
use rekamind_recorder::local_backend::LocalBackend;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// A stand-in for `rekamind-backend engines ...` written in sh: the real one is exercised end to end
/// against the frozen binary in CI; here we test how the app drives *any* such program.
fn tool(dir: &std::path::Path, body: &str) -> EngineTool {
    let p = dir.join("fake-engines.sh");
    std::fs::write(&p, format!("#!/bin/sh\n{body}\n")).unwrap();
    // Run through `sh` rather than exec'ing the file: executing a just-written file races with other
    // tests' forks inheriting its write handle (ETXTBSY).
    EngineTool {
        program: "sh".into(),
        prefix: vec![p.to_string_lossy().into_owned(), "engines".into()],
        env: vec![("FAKE".into(), "yes".into())],
    }
}

#[test]
fn status_reads_the_last_line_even_when_libraries_print_noise_first() {
    let d = tempfile::tempdir().unwrap();
    let t = tool(
        d.path(),
        r#"echo "UserWarning: something"; echo '{"asr":true,"kind":"cpu"}'"#,
    );
    let v = t.status().unwrap();
    assert_eq!(v["asr"], true);
    assert_eq!(v["kind"], "cpu");
}

#[test]
fn a_program_that_prints_no_json_gives_an_error_that_says_what_it_complained_about() {
    let d = tempfile::tempdir().unwrap();
    let t = tool(d.path(), r#"echo "Traceback: boom" >&2; exit 3"#);
    let e = t.status().unwrap_err();
    assert!(e.contains("boom"), "{e}");
    let missing = EngineTool {
        program: "/no/such/prog".into(),
        prefix: vec![],
        env: vec![],
    };
    assert!(missing.status().unwrap_err().contains("/no/such/prog"));
}

#[test]
fn check_failing_is_an_answer_not_an_error() {
    let d = tempfile::tempdir().unwrap();
    let t = tool(
        d.path(),
        r#"echo '{"ok":false,"error":"ImportError: x"}'; exit 1"#,
    );
    assert_eq!(t.check().unwrap()["ok"], false);
}

#[test]
fn install_streams_stdout_and_stderr_lines_and_passes_arguments_and_env() {
    let d = tempfile::tempdir().unwrap();
    let t = tool(
        d.path(),
        r#"echo "args: $@ env: $FAKE"; echo "downloading" >&2; echo "done""#,
    );
    let mut lines = Vec::new();
    t.run_streaming(&["install", "cpu"], &AtomicBool::new(false), &mut |l| {
        lines.push(l.to_string())
    })
    .unwrap();
    assert!(
        lines.contains(&"args: engines install cpu env: yes".to_string()),
        "{lines:?}"
    );
    assert!(lines.contains(&"downloading".to_string()) && lines.contains(&"done".to_string()));
}

#[test]
fn a_failed_install_reports_the_last_line() {
    let d = tempfile::tempdir().unwrap();
    let t = tool(
        d.path(),
        r#"echo "working"; echo "ERROR: no matching distribution" >&2; exit 1"#,
    );
    let e = t
        .run_streaming(&["install", "cuda"], &AtomicBool::new(false), &mut |_| {})
        .unwrap_err();
    assert!(e.contains("no matching distribution"), "{e}");
}

#[test]
fn cancelling_stops_a_long_install_promptly() {
    let d = tempfile::tempdir().unwrap();
    let t = tool(d.path(), r#"echo started; sleep 30"#);
    let cancel = Arc::new(AtomicBool::new(false));
    let c2 = cancel.clone();
    let started = Instant::now();
    let h = std::thread::spawn(move || {
        let c3 = c2.clone();
        t.run_streaming(&["install", "cpu"], &c2, &mut |l| {
            if l == "started" {
                c3.store(true, Ordering::SeqCst);
            }
        })
    });
    let r = h.join().unwrap();
    assert_eq!(r.unwrap_err(), "Dibatalkan.");
    assert!(started.elapsed() < Duration::from_secs(10));
}

#[test]
fn a_backend_that_dies_at_startup_explains_why_from_its_log() {
    let d = tempfile::tempdir().unwrap();
    let log = d.path().join("logs").join("backend.log");
    let sh = d.path().join("dies.sh");
    std::fs::write(
        &sh,
        "#!/bin/sh\necho 'ImportError: libfoo.so missing' >&2\nexit 7\n",
    )
    .unwrap();
    let lb = Arc::new(
        LocalBackend::new(
            "sh",
            vec![sh.to_string_lossy().into_owned()],
            vec![],
            "http://127.0.0.1:1",
        )
        .with_log(&log),
    );
    let e = lb.ensure(Duration::from_secs(5)).unwrap_err();
    assert!(e.contains("libfoo.so missing"), "{e}");
    assert!(std::fs::read_to_string(&log).unwrap().contains("libfoo"));
}

#[test]
fn a_stranger_already_on_our_port_is_reported_instead_of_failing_every_request() {
    // Found on the installed app: a backend left over from an earlier run (other secret) was healthy,
    // so it was "used", and the UI then showed "Token lokal tidak valid" for everything.
    let d = tempfile::tempdir().unwrap();
    let port = {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        l.local_addr().unwrap().port()
    };
    let script = d.path().join("stranger.py");
    std::fs::write(
        &script,
        format!(
            r#"
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/api/health": code, body = 200, {{"status": "ok"}}
        else: code, body = 401, {{"detail": "Token lokal tidak valid."}}
        b = json.dumps(body).encode(); self.send_response(code)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
http.server.HTTPServer(("127.0.0.1", {port}), H).serve_forever()
"#
        ),
    )
    .unwrap();
    let mut stranger = std::process::Command::new("python3")
        .arg(&script)
        .spawn()
        .unwrap();
    let url = format!("http://127.0.0.1:{port}");
    let t = Instant::now();
    while Instant::now() - t < Duration::from_secs(10)
        && !LocalBackend::new("x", vec![], vec![], url.clone()).is_healthy()
    {
        std::thread::sleep(Duration::from_millis(50));
    }
    let lb = LocalBackend::new("never-started", vec![], vec![], url).with_token("ours");
    let e = lb.ensure(Duration::from_secs(5)).unwrap_err();
    assert!(
        e.contains(&format!("Port {port}")) && e.contains("dipakai program lain"),
        "{e}"
    );
    assert!(
        !lb.owns_process(),
        "we must not claim, or kill, a process we did not start"
    );
    let _ = stranger.kill();
    let _ = stranger.wait();
}
