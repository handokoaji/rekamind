use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use crate::meter::Meter;
use crate::wav::WavWriter;
use crate::{Source, SAMPLE_RATE};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SourceState {
    Recording,
    /// The device went away (headset unplugged, default device changed); trying again.
    Reconnecting,
    /// Could not be opened at all; the rest of the recording carries on without it.
    Unavailable(String),
    /// Broke mid-recording and could not recover. What was captured so far is kept.
    Failed(String),
}

/// What a capture backend talks to. All methods are cheap and non-blocking in the common case:
/// they run on the real-time capture thread.
pub struct SourceCtx {
    pub source: Source,
    writer: Mutex<Option<WavWriter>>,
    meter: Meter,
    samples: AtomicU64,
    state: Mutex<SourceState>,
    stopping: AtomicBool,
}

impl SourceCtx {
    pub fn create(source: Source, path: &Path) -> std::io::Result<Arc<Self>> {
        Ok(Arc::new(Self {
            source,
            writer: Mutex::new(Some(WavWriter::create(path, SAMPLE_RATE)?)),
            meter: Meter::default(),
            samples: AtomicU64::new(0),
            state: Mutex::new(SourceState::Recording),
            stopping: AtomicBool::new(false),
        }))
    }

    pub fn push(&self, samples: &[i16]) {
        if samples.is_empty() {
            return;
        }
        let mut guard = self.writer.lock().unwrap();
        let Some(w) = guard.as_mut() else { return };
        if let Err(e) = w.write_samples(samples) {
            // Disk full or removed: stop writing, tell the user, never panic on the capture thread.
            *guard = None;
            drop(guard);
            self.set_state(SourceState::Failed(format!(
                "tidak bisa menulis ke disk: {e}"
            )));
            return;
        }
        self.samples.store(w.samples(), Ordering::Relaxed);
        drop(guard);
        self.meter.update(samples);
    }

    /// Write `n` samples of silence (timeline padding), without moving the level meter.
    pub fn push_silence(&self, mut n: usize) {
        const BLOCK: [i16; 4096] = [0; 4096];
        while n > 0 {
            let k = n.min(BLOCK.len());
            self.push(&BLOCK[..k]);
            n -= k;
        }
    }

    pub fn samples(&self) -> u64 {
        self.samples.load(Ordering::Relaxed)
    }
    pub fn take_level(&self) -> f32 {
        self.meter.take_peak()
    }
    pub fn state(&self) -> SourceState {
        self.state.lock().unwrap().clone()
    }
    pub fn set_state(&self, s: SourceState) {
        let mut cur = self.state.lock().unwrap();
        // A terminal state must not be overwritten by a late "recovered" from another thread.
        if !matches!(*cur, SourceState::Failed(_) | SourceState::Unavailable(_))
            || matches!(s, SourceState::Failed(_))
        {
            *cur = s;
        }
    }
    pub fn is_stopping(&self) -> bool {
        self.stopping.load(Ordering::Relaxed)
    }
    pub(crate) fn begin_stop(&self) {
        self.stopping.store(true, Ordering::Relaxed);
    }

    /// Close the file. Called once, after the capture thread has been joined.
    pub(crate) fn finish(&self) -> std::io::Result<u64> {
        match self.writer.lock().unwrap().take() {
            Some(w) => w.finish(),
            None => Ok(self.samples()),
        }
    }
}
