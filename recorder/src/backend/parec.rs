//! Linux: PulseAudio / PipeWire (via its Pulse compatibility) through `parec`.
//!
//! A subprocess, not a native binding, on purpose: no libpulse/ALSA headers to build against,
//! and the sound server does the resampling to 16 kHz mono for us, so this process does almost
//! nothing but copy bytes.

use std::io::Read;
use std::os::fd::AsRawFd;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Instant;

use super::{Backend, Capture};
use crate::sink::{SourceCtx, SourceState};
use crate::timeline::Pacer;
use crate::{Source, SAMPLE_RATE};

pub struct ParecBackend {
    command: String,
}

impl ParecBackend {
    pub fn new() -> Self {
        Self {
            command: std::env::var("REKAMIND_PAREC").unwrap_or_else(|_| "parec".into()),
        }
    }
    pub fn with_command(command: impl Into<String>) -> Self {
        Self {
            command: command.into(),
        }
    }
}

impl Default for ParecBackend {
    fn default() -> Self {
        Self::new()
    }
}

struct Running {
    stop: Arc<AtomicBool>,
    child: Arc<std::sync::Mutex<Child>>,
    thread: Option<JoinHandle<()>>,
}

impl Capture for Running {
    fn stop(mut self: Box<Self>) {
        self.stop.store(true, Ordering::Relaxed);
        let _ = self.child.lock().unwrap().kill();
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
        let _ = self.child.lock().unwrap().wait();
    }
}

fn poll_readable(fd: i32, timeout_ms: i32) -> bool {
    let mut p = libc::pollfd {
        fd,
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: `p` is a valid pollfd for the duration of the call; nfds = 1.
    let r = unsafe { libc::poll(&mut p, 1, timeout_ms) };
    r > 0
}

impl Backend for ParecBackend {
    fn start(&self, ctx: Arc<SourceCtx>) -> Result<Box<dyn Capture>, String> {
        let device = match ctx.source {
            Source::Mic => "@DEFAULT_SOURCE@",
            Source::Speaker => "@DEFAULT_MONITOR@",
        };
        let mut child = Command::new(&self.command)
            .args(["--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=200", "--client-name=rekamind"])
            .arg(format!("--device={device}"))
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .stdin(Stdio::null())
            .spawn()
            .map_err(|e| format!("tidak bisa menjalankan `{}` ({e}). Pasang pulseaudio-utils (atau pipewire-pulse).", self.command))?;
        let mut stdout = child.stdout.take().ok_or("stdout parec tidak tersedia")?;
        let fd = stdout.as_raw_fd();
        let child = Arc::new(std::sync::Mutex::new(child));
        let stop = Arc::new(AtomicBool::new(false));

        let (flag, child2) = (stop.clone(), child.clone());
        let thread = thread::spawn(move || {
            let mut pacer = Pacer::new(Instant::now(), SAMPLE_RATE);
            let mut raw = [0u8; 8192];
            let mut carry: Option<u8> = None; // a sample split across two reads
            let mut samples: Vec<i16> = Vec::with_capacity(4096);
            while !flag.load(Ordering::Relaxed) {
                if !poll_readable(fd, 250) {
                    // Nothing arrived: a suspended monitor. Keep the timeline moving.
                    let gap = pacer.gap(Instant::now());
                    if gap > 0 {
                        ctx.push_silence(gap);
                        pacer.wrote(gap);
                    }
                    continue;
                }
                match stdout.read(&mut raw) {
                    Ok(0) | Err(_) => {
                        if !flag.load(Ordering::Relaxed) {
                            let status = child2.lock().unwrap().try_wait().ok().flatten();
                            ctx.set_state(SourceState::Failed(format!(
                                "parec berhenti tiba-tiba ({status:?})"
                            )));
                        }
                        return;
                    }
                    Ok(n) => {
                        samples.clear();
                        let mut bytes = &raw[..n];
                        if let Some(lo) = carry.take() {
                            samples.push(i16::from_le_bytes([lo, bytes[0]]));
                            bytes = &bytes[1..];
                        }
                        let mut pairs = bytes.chunks_exact(2);
                        samples.extend(pairs.by_ref().map(|p| i16::from_le_bytes([p[0], p[1]])));
                        carry = pairs.remainder().first().copied();
                        // Catch up first if there was a silent stretch before this data.
                        let gap = pacer.gap(Instant::now()).saturating_sub(samples.len());
                        if gap > 0 {
                            ctx.push_silence(gap);
                            pacer.wrote(gap);
                        }
                        ctx.push(&samples);
                        pacer.wrote(samples.len());
                    }
                }
            }
        });
        Ok(Box::new(Running {
            stop,
            child,
            thread: Some(thread),
        }))
    }
}
