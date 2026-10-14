use std::sync::atomic::{AtomicU32, Ordering};

/// Peak level since the last read, for the UI's "is it actually recording?" indicator.
/// One relaxed atomic max per audio chunk: effectively free.
#[derive(Default)]
pub struct Meter {
    peak: AtomicU32,
}

impl Meter {
    pub fn update(&self, samples: &[i16]) {
        let m = samples
            .iter()
            .map(|s| s.unsigned_abs() as u32)
            .max()
            .unwrap_or(0);
        self.peak.fetch_max(m, Ordering::Relaxed);
    }

    /// 0.0 ..= 1.0, and resets so the next read reflects only what happened since.
    pub fn take_peak(&self) -> f32 {
        (self.peak.swap(0, Ordering::Relaxed) as f32 / 32768.0).min(1.0)
    }
}
