//! Fake audio for tests, demos and machines with no audio hardware. Also what the CI and the
//! end-to-end check against the real backend use.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use super::{Backend, Capture};
use crate::sink::{SourceCtx, SourceState};
use crate::{Source, SAMPLE_RATE};

#[derive(Clone)]
pub struct Script {
    pub hz: f32,
    pub amplitude: f32,
    /// Stop producing audio (but keep the source "recording") after this long.
    pub active_ms: u64,
    /// Simulate the device dying this long after start.
    pub fail_after_ms: Option<u64>,
    /// Refuse to open at all.
    pub unavailable: Option<String>,
    /// Pace in real time (true) or as fast as possible (false, for tests).
    pub realtime: bool,
    /// Skip the first N ms, like loopback delivering nothing while the computer is silent.
    pub silent_gap_ms: u64,
}

impl Default for Script {
    fn default() -> Self {
        Self {
            hz: 440.0,
            amplitude: 0.3,
            active_ms: 1_000,
            fail_after_ms: None,
            unavailable: None,
            realtime: false,
            silent_gap_ms: 0,
        }
    }
}

pub struct SyntheticBackend {
    pub mic: Script,
    pub speaker: Script,
}

impl SyntheticBackend {
    pub fn new(mic: Script, speaker: Script) -> Self {
        Self { mic, speaker }
    }
}

struct Running {
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl Capture for Running {
    fn stop(mut self: Box<Self>) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

impl Backend for SyntheticBackend {
    fn start(&self, ctx: Arc<SourceCtx>) -> Result<Box<dyn Capture>, String> {
        let script = match ctx.source {
            Source::Mic => self.mic.clone(),
            Source::Speaker => self.speaker.clone(),
        };
        if let Some(msg) = &script.unavailable {
            return Err(msg.clone());
        }
        let stop = Arc::new(AtomicBool::new(false));
        let flag = stop.clone();
        let thread = thread::spawn(move || {
            let chunk = (SAMPLE_RATE / 50) as usize; // 20 ms
            let total = (SAMPLE_RATE as u64 * script.active_ms / 1000) as usize;
            let skip = (SAMPLE_RATE as u64 * script.silent_gap_ms / 1000) as usize;
            let started = Instant::now();
            let mut n = 0usize;
            let mut buf = vec![0i16; chunk];
            if skip > 0 {
                ctx.push_silence(skip); // what the pacer would insert for a silent loopback
                n += skip;
            }
            while !flag.load(Ordering::Relaxed) {
                if let Some(f) = script.fail_after_ms {
                    if started.elapsed() >= Duration::from_millis(f)
                        || (!script.realtime && n * 1000 / SAMPLE_RATE as usize >= f as usize)
                    {
                        ctx.set_state(SourceState::Failed("perangkat terputus (simulasi)".into()));
                        return;
                    }
                }
                if n < total {
                    for (i, s) in buf.iter_mut().enumerate() {
                        let t = (n + i) as f32 / SAMPLE_RATE as f32;
                        *s = ((2.0 * std::f32::consts::PI * script.hz * t).sin()
                            * script.amplitude
                            * 32767.0) as i16;
                    }
                    ctx.push(&buf);
                    n += chunk;
                    if script.realtime {
                        thread::sleep(Duration::from_millis(20));
                    }
                } else {
                    thread::sleep(Duration::from_millis(5)); // idle until stopped
                }
            }
        });
        Ok(Box::new(Running {
            stop,
            thread: Some(thread),
        }))
    }
}
