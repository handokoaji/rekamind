//! Managing the optional "engine pack" (faster-whisper, pyannote) through the backend program itself:
//! `rekamind-backend engines status|check|install|warmup`. The pack is several GB and depends on the
//! hardware, so it is installed on demand instead of being baked into the installer.

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use serde_json::Value;

use crate::local_backend::hide_window;

#[derive(Clone, Debug)]
pub struct EngineTool {
    pub program: String,
    /// Arguments that select the `engines` command ("engines", or "-m rekamind_server.enginepack").
    pub prefix: Vec<String>,
    pub env: Vec<(String, String)>,
}

impl EngineTool {
    fn command(&self, args: &[&str]) -> Command {
        let mut c = Command::new(&self.program);
        c.args(&self.prefix)
            .args(args)
            .envs(self.env.iter().cloned())
            .stdin(Stdio::null());
        c
    }

    /// Run a short command that prints one JSON document; the *last* non-empty stdout line is it
    /// (libraries are free to print warnings first).
    fn json(&self, args: &[&str]) -> Result<Value, String> {
        let mut c = self.command(args);
        c.stdout(Stdio::piped()).stderr(Stdio::piped());
        let out = hide_window(&mut c)
            .output()
            .map_err(|e| format!("tidak bisa menjalankan `{}`: {e}", self.program))?;
        let text = String::from_utf8_lossy(&out.stdout);
        let last = text
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("");
        serde_json::from_str(last).map_err(|_| {
            format!(
                "jawaban tidak terbaca dari `{}` ({}): {}",
                self.program,
                out.status,
                String::from_utf8_lossy(&out.stderr)
                    .lines()
                    .last()
                    .unwrap_or("")
            )
        })
    }

    /// Is the pack installed? Cheap: imports nothing heavy.
    pub fn status(&self) -> Result<Value, String> {
        self.json(&["status"])
    }

    /// Really import the engines. `{ok:false,error}` is a normal answer, not an `Err`.
    pub fn check(&self) -> Result<Value, String> {
        self.json(&["check"])
    }

    /// Run a long command (`install`, `warmup`), passing every output line to `on_line`. Setting
    /// `cancel` kills it. Err carries the last output line when the command fails.
    pub fn run_streaming(
        &self,
        args: &[&str],
        cancel: &AtomicBool,
        on_line: &mut dyn FnMut(&str),
    ) -> Result<(), String> {
        let mut c = self.command(args);
        c.stdout(Stdio::piped()).stderr(Stdio::piped());
        let mut child = hide_window(&mut c)
            .spawn()
            .map_err(|e| format!("tidak bisa menjalankan `{}`: {e}", self.program))?;
        let (tx, rx) = mpsc::channel::<String>();
        let mut readers = Vec::new();
        if let Some(o) = child.stdout.take() {
            let tx = tx.clone();
            readers.push(thread::spawn(move || pump(BufReader::new(o), tx)));
        }
        if let Some(e) = child.stderr.take() {
            let tx = tx.clone();
            readers.push(thread::spawn(move || pump(BufReader::new(e), tx)));
        }
        drop(tx);
        let mut tail: std::collections::VecDeque<String> = std::collections::VecDeque::new();
        let mut cancelled_at: Option<std::time::Instant> = None;
        loop {
            if cancel.load(Ordering::SeqCst) && cancelled_at.is_none() {
                cancelled_at = Some(std::time::Instant::now());
                let _ = child.kill();
            }
            // A grandchild may inherit the pipes and outlive the kill; do not wait for it to close them.
            if cancelled_at.is_some_and(|t| t.elapsed() > Duration::from_millis(500)) {
                break;
            }
            match rx.recv_timeout(Duration::from_millis(100)) {
                Ok(line) => {
                    if !line.trim().is_empty() {
                        // stdout and stderr arrive from two threads, so the "last" line is not
                        // reliably the error: keep a few.
                        tail.push_back(line.clone());
                        if tail.len() > 4 {
                            tail.pop_front();
                        }
                    }
                    on_line(&line);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
            }
        }
        let cancelled = cancelled_at.is_some();
        if !cancelled {
            for r in readers {
                let _ = r.join();
            }
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        if cancelled {
            return Err("Dibatalkan.".into());
        }
        if status.success() {
            Ok(())
        } else {
            Err(format!("gagal ({status}): {}", Vec::from(tail).join(" | ")))
        }
    }
}

fn pump<R: BufRead>(r: R, tx: mpsc::Sender<String>) {
    for line in r.lines().map_while(Result::ok) {
        if tx.send(line).is_err() {
            break;
        }
    }
}
