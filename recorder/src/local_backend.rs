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

pub struct LocalBackend {
    program: String,
    args: Vec<String>,
    env: Vec<(String, String)>,
    url: String,
    token: Option<String>,
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
            child: Mutex::new(None),
            idle_since: Mutex::new(None),
        }
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
            return Ok(());
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
                let child = Command::new(&self.program)
                    .args(&self.args)
                    .envs(self.env.iter().cloned())
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
                    .map_err(|e| {
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
                return Ok(());
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
                return Err(format!(
                    "mesin pemrosesan lokal berhenti saat dinyalakan ({status})"
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
