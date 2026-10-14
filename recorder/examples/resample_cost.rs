use rekamind_recorder::resample::Resampler;
fn main() {
    let mut r = Resampler::new(48_000, 16_000, 2);
    let block: Vec<f32> = (0..96_000)
        .map(|i| ((i / 2) as f32 * 0.03).sin() * 0.3)
        .collect();
    let t = std::time::Instant::now();
    let mut out = Vec::new();
    for _ in 0..600 {
        out.clear();
        r.process(&block, &mut out);
    } // 10 min
    let s = t.elapsed().as_secs_f64();
    println!(
        "10 menit audio 48 kHz stereo -> 16 kHz mono: {:.2} dtk CPU = {:.3}% dari satu core",
        s,
        s / 600.0 * 100.0
    );
}
