//! Streaming resampler to 16 kHz mono, used only when the OS cannot convert for us.
//!
//! Windowed-sinc interpolation evaluated at the exact fractional position of every output
//! sample, so it handles any ratio (44.1k, 48k, 96k...) and low-passes below the output
//! Nyquist first, which a naive "take every third sample" would not (that aliases).

/// Table resolution: kernel samples per input sample. Linear interpolation between entries.
const PHASES: usize = 512;

pub struct Resampler {
    channels: usize,
    /// Windowed-sinc kernel for t = 0..half, `PHASES` entries per unit. Computed once, so the
    /// per-sample cost is multiply-adds only (no sin/cos on the hot path).
    table: Vec<f32>,
    /// Input samples advanced per output sample.
    step: f64,
    half: usize,
    hist: Vec<f32>,
    /// Position of the next output sample in `hist`, in input samples.
    pos: f64,
}

fn sinc(x: f64) -> f64 {
    if x.abs() < 1e-9 {
        1.0
    } else {
        let px = std::f64::consts::PI * x;
        px.sin() / px
    }
}

impl Resampler {
    pub fn new(in_rate: u32, out_rate: u32, channels: usize) -> Self {
        let step = in_rate as f64 / out_rate as f64;
        let fc = (0.95 / step.max(1.0)).min(0.95);
        let half = (8.0 / fc).ceil() as usize;
        let table = (0..=half * PHASES + 1)
            .map(|i| {
                let t = i as f64 / PHASES as f64;
                let w = if t < half as f64 {
                    0.5 * (1.0 + (std::f64::consts::PI * t / half as f64).cos())
                } else {
                    0.0
                }; // Hann
                (fc * sinc(fc * t) * w) as f32
            })
            .collect();
        Self {
            channels: channels.max(1),
            table,
            step,
            half,
            hist: vec![0.0; half],
            pos: half as f64,
        }
    }

    /// Feed interleaved f32 frames; appends converted samples to `out`.
    pub fn process(&mut self, interleaved: &[f32], out: &mut Vec<i16>) {
        let ch = self.channels;
        for frame in interleaved.chunks_exact(ch) {
            self.hist.push(frame.iter().sum::<f32>() / ch as f32); // downmix by averaging
        }
        let half = self.half as isize;
        loop {
            let base = self.pos.floor() as isize;
            if base + half >= self.hist.len() as isize {
                break;
            }
            let (mut acc, mut wsum) = (0.0f32, 0.0f32);
            for k in (base - half + 1)..=(base + half) {
                let idx = (self.pos - k as f64).abs() * PHASES as f64;
                let i = idx as usize;
                let frac = (idx - i as f64) as f32;
                let h = self.table[i] + (self.table[i + 1] - self.table[i]) * frac;
                acc += self.hist[k as usize] * h;
                wsum += h;
            }
            let y = if wsum.abs() > 1e-6 {
                (acc / wsum) as f64
            } else {
                0.0
            }; // exact unity gain at DC
            out.push((y * 32767.0).round().clamp(-32768.0, 32767.0) as i16);
            self.pos += self.step;
        }
        // Drop what can no longer be touched, keeping memory flat for hour-long meetings.
        let keep_from = (self.pos.floor() as usize).saturating_sub(self.half);
        if keep_from > 4096 {
            self.hist.drain(..keep_from);
            self.pos -= keep_from as f64;
        }
    }
}

/// i16 <-> f32 helpers shared by backends.
pub fn i16_to_f32(s: &[i16], out: &mut Vec<f32>) {
    out.extend(s.iter().map(|v| *v as f32 / 32768.0));
}
