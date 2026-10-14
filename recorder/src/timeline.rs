//! Keeping two files on the same clock.
//!
//! The microphone delivers samples continuously, but WASAPI loopback (and a suspended
//! PulseAudio monitor) delivers *nothing* while the computer is silent. Written naively, the
//! speaker file would be shorter than the meeting and every later word would be placed too
//! early relative to the mic -- scrambling the transcript order. The pacer turns elapsed wall
//! time into the silence that must be inserted to stay aligned.

use std::time::Instant;

pub struct Pacer {
    start: Instant,
    rate: u32,
    written: u64,
}

/// Don't pad for jitter; a real gap is longer than this.
const MIN_GAP_MS: u64 = 120;

impl Pacer {
    pub fn new(start: Instant, rate: u32) -> Self {
        Self {
            start,
            rate,
            written: 0,
        }
    }

    pub fn expected(&self, now: Instant) -> u64 {
        (now.saturating_duration_since(self.start).as_secs_f64() * self.rate as f64) as u64
    }

    /// Number of zero samples to insert now to catch up with the wall clock (0 if on time).
    pub fn gap(&self, now: Instant) -> usize {
        let expected = self.expected(now);
        let behind = expected.saturating_sub(self.written);
        if behind * 1000 >= MIN_GAP_MS * self.rate as u64 {
            behind as usize
        } else {
            0
        }
    }

    pub fn wrote(&mut self, n: usize) {
        self.written += n as u64;
    }
}
