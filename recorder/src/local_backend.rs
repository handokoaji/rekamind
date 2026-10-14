//! A backend that lives on this computer only while there is work for it.
//!
//! Recording must be featherweight, and transcription models are the opposite (gigabytes).
//! So the desktop app does not keep the Python backend resident: it starts it when a recording
//! needs processing and stops it again once the queue has been empty for a while, which also
//! frees the GPU for whatever the user does next.

use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::api::Client;

/// A console program started by a GUI app must not flash a console window on Windows.
pub(crate) fn hide_window(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd
}

/// The last few lines of a log, for an error message that says *why* instead of just "it stopped".
pub(crate) fn log_tail(path: &std::path::Path, lines: usize) -> String {
    let text = std::fs::read(path)
        .map(|b| String::from_utf8_lossy(&b[b.len().saturating_sub(8192)..]).into_owned())
        .unwrap_or_default();
    let all: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    all[all.len().saturating_sub(lines)..].join("\n")
}

pub struct LocalBackend {
    program: String,
    args: Vec<String>,
    env: Vec<(String, String)>,
    url: String,
    token: Option<String>,
    /// Where the backend's output goes (None: discarded). Also quoted in start-up errors.
    log: Option<std::path::PathBuf>,
    /// Only a process *we* started is ours to stop; an already-running backend is left alone.
    child: Mutex<Option<Child>>,
    idle_since: Mutex<Option<Instant>>,
}

impl LocalBackend {
    pub fn new(
        program: impl Into<String>,
        args: Vec<String>,
        env: Vec<(String, String)>,
        url: impl Into<String>,
    ) -> Self {
        Self {
            program: program.into(),
            args,
            env,
            url: url.into(),
            token: None,
            log: None,
            child: Mutex::new(None),
            idle_since: Mutex::new(None),
        }
    }

    /// Append the backend's stdout/stderr to this file.
    pub fn with_log(mut self, path: impl Into<std::path::PathBuf>) -> Self {
        self.log = Some(path.into());
        self
    }

    fn output(&self) -> (Stdio, Stdio) {
        let file = self.log.as_ref().and_then(|p| {
            if let Some(d) = p.parent() {
                let _ = std::fs::create_dir_all(d);
            }
            std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(p)
                .ok()
        });
        match file.and_then(|f| f.try_clone().ok().map(|g| (f, g))) {
            Some((a, b)) => (Stdio::from(a), Stdio::from(b)),
            None => (Stdio::null(), Stdio::null()),
        }
    }

    /// The credential this backend demands (`REKAMIND_LOCAL_TOKEN`); needed to ask it whether it is busy.
    pub fn with_token(mut self, token: impl Into<String>) -> Self {
        self.token = Some(token.into());
        self
    }

    fn client(&self) -> Client {
        Client::new(&self.url, self.token.clone())
    }

    pub fn is_healthy(&self) -> bool {
        self.client().health().is_ok()
    }

    pub fn owns_process(&self) -> bool {
        self.child.lock().unwrap().is_some()
    }

    /// Make sure a backend is answering at `url`, starting one if needed.
    pub fn ensure(&self, timeout: Duration) -> Result<(), String> {
        if self.is_healthy() {
            return self.verify_ours();
        }
        {
            let mut guard = self.child.lock().unwrap();
            // A previous child that died (crash, killed) must not block a fresh start.
            if let Some(c) = guard.as_mut() {
                if c.try_wait().ok().flatten().is_some() {
                    *guard = None;
                }
            }
            if guard.is_none() {
                let (out, err) = self.output();
                let mut cmd = Command::new(&self.program);
                cmd.args(&self.args)
                    .envs(self.env.iter().cloned())
                    .stdin(Stdio::null())
                    .stdout(out)
                    .stderr(err);
                let child = hide_window(&mut cmd).spawn().map_err(|e| {
                    format!(
                        "tidak bisa menyalakan mesin pemrosesan lokal (`{}`): {e}",
                        self.program
                    )
                })?;
                *guard = Some(child);
            }
        }
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if self.is_healthy() {
                *self.idle_since.lock().unwrap() = None;
                return self.verify_ours();
            }
            // One lock scope: holding the guard while locking again would deadlock (Mutex is not reentrant).
            let exited = {
                let mut guard = self.child.lock().unwrap();
                let status = guard.as_mut().and_then(|c| c.try_wait().ok().flatten());
                if status.is_some() {
                    *guard = None;
                }
                status
            };
            if let Some(status) = exited {
                let why = self
                    .log
                    .as_deref()
                    .map(|p| log_tail(p, 6))
                    .unwrap_or_default();
                return Err(format!(
                    "mesin pemrosesan lokal berhenti saat dinyalakan ({status}){}",
                    if why.is_empty() {
                        String::new()
                    } else {
                        format!(":\n{why}")
                    }
                ));
            }
            thread::sleep(Duration::from_millis(200));
        }
        self.stop();
        Err(format!(
            "mesin pemrosesan lokal tidak siap setelah {} detik",
            timeout.as_secs()
        ))
    }

    /// Something answers on our port. If we did not start it, check that it honours our secret: a
    /// leftover backend from an earlier run (different secret) would otherwise make every request
    /// fail with a confusing "invalid token".
    fn verify_ours(&self) -> Result<(), String> {
        if self.token.is_none() || self.owns_process() {
            return Ok(());
        }
        match self.client().accepts_credential() {
            Ok(false) => Err(format!(
                "Port {} sudah dipakai program lain (kemungkinan sisa Rekamind sebelumnya). \
                 Tutup program itu atau ubah port di Pengaturan → Lanjutan, lalu coba lagi.",
                self.url.rsplit(':').next().unwrap_or("?")
            )),
            _ => Ok(()),
        }
    }

    pub fn stop(&self) {
        if let Some(mut c) = self.child.lock().unwrap().take() {
            let _ = c.kill();
            let _ = c.wait();
        }
        *self.idle_since.lock().unwrap() = None;
    }

    /// Stop the backend if we own it and it has nothing queued or running. A busy one is left alone:
    /// killing a running transcription would only throw the work away.
    pub fn stop_if_idle(&self) -> bool {
        if !self.owns_process() {
            return false;
        }
        if matches!(self.client().has_active_jobs(), Ok(false)) {
            self.stop();
            return true;
        }
        false
    }

    /// Call periodically. Stops the backend we started once nothing has been queued or running
    /// for `idle_after`. Returns true if it stopped it.
    pub fn idle_tick(&self, idle_after: Duration) -> bool {
        if !self.owns_process() {
            return false;
        }
        match self.client().has_active_jobs() {
            Ok(true) => {
                *self.idle_since.lock().unwrap() = None;
                false
            }
            Ok(false) => {
                let mut since = self.idle_since.lock().unwrap();
                let started = *since.get_or_insert_with(Instant::now);
                if started.elapsed() >= idle_after {
                    drop(since);
                    self.stop();
                    true
                } else {
                    false
                }
            }
            // Cannot tell: never kill a backend that might be mid-transcription.
            Err(_) => false,
        }
    }
}

impl Drop for LocalBackend {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Background thread that runs `idle_tick` every `every` until dropped.
pub struct Watcher {
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl Watcher {
    pub fn start(backend: Arc<LocalBackend>, idle_after: Duration, every: Duration) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let flag = stop.clone();
        let thread = thread::spawn(move || {
            let mut slept = Duration::ZERO;
            while !flag.load(Ordering::Relaxed) {
                thread::sleep(Duration::from_millis(100));
                slept += Duration::from_millis(100);
                if slept >= every {
                    slept = Duration::ZERO;
                    backend.idle_tick(idle_after);
                }
            }
        });
        Self {
            stop,
            thread: Some(thread),
        }
    }
}

impl Drop for Watcher {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}
