use rekamind_recorder::resample::Resampler;

fn sine(hz: f32, rate: u32, secs: f32, amp: f32) -> Vec<f32> {
    (0..(rate as f32 * secs) as usize)
        .map(|i| (2.0 * std::f32::consts::PI * hz * i as f32 / rate as f32).sin() * amp)
        .collect()
}
fn rms(s: &[i16]) -> f64 {
    (s.iter().map(|v| (*v as f64).powi(2)).sum::<f64>() / s.len() as f64).sqrt()
}
fn run(r: &mut Resampler, input: &[f32]) -> Vec<i16> {
    let mut out = Vec::new();
    r.process(input, &mut out);
    out
}

#[test]
fn passes_speech_band_tones_at_full_level() {
    for (rate, hz) in [
        (48_000, 1000.0),
        (44_100, 1000.0),
        (96_000, 440.0),
        (48_000, 3000.0),
    ] {
        let mut r = Resampler::new(rate, 16_000, 1);
        let out = run(&mut r, &sine(hz, rate, 1.0, 0.5));
        let body = &out[800..out.len() - 800]; // skip filter warm-up/tail
        let expected = 0.5 * 32767.0 / 2f64.sqrt();
        assert!(
            (rms(body) - expected).abs() / expected < 0.03,
            "{rate}->16k {hz}Hz: rms {} vs {}",
            rms(body),
            expected
        );
    }
}

#[test]
fn output_length_follows_the_ratio() {
    for rate in [48_000u32, 44_100, 32_000, 16_000, 8_000] {
        let mut r = Resampler::new(rate, 16_000, 1);
        let out = run(&mut r, &vec![0.0; rate as usize * 2]);
        let want = 32_000i64;
        assert!(
            (out.len() as i64 - want).abs() <= 40,
            "{rate}: got {} want ~{want}",
            out.len()
        );
    }
}

#[test]
fn tones_above_the_new_nyquist_are_removed_not_aliased() {
    // 12 kHz at 48 kHz would fold down to 4 kHz if we just dropped samples.
    let mut r = Resampler::new(48_000, 16_000, 1);
    let out = run(&mut r, &sine(12_000.0, 48_000, 1.0, 0.8));
    let body = &out[800..out.len() - 800];
    assert!(
        rms(body) < 0.01 * 0.8 * 32767.0,
        "aliased energy leaked through: rms {}",
        rms(body)
    );
}

#[test]
fn chunking_does_not_change_the_result() {
    let input = sine(700.0, 48_000, 0.5, 0.4);
    let whole = run(&mut Resampler::new(48_000, 16_000, 1), &input);
    let mut r = Resampler::new(48_000, 16_000, 1);
    let mut pieces = Vec::new();
    for c in input.chunks(333) {
        r.process(c, &mut pieces);
    }
    assert_eq!(whole, pieces);
}

#[test]
fn stereo_is_downmixed_by_averaging() {
    let mut r = Resampler::new(48_000, 16_000, 2);
    let mono = sine(500.0, 48_000, 0.5, 0.5);
    let stereo: Vec<f32> = mono.iter().flat_map(|s| [*s, *s]).collect();
    let both = run(&mut r, &stereo);
    let single = run(&mut Resampler::new(48_000, 16_000, 1), &mono);
    assert_eq!(both, single);
    let antiphase: Vec<f32> = mono.iter().flat_map(|s| [*s, -*s]).collect();
    assert!(
        rms(&run(&mut Resampler::new(48_000, 16_000, 2), &antiphase)) < 5.0,
        "L=-R must cancel"
    );
}

#[test]
fn memory_stays_flat_over_a_long_stream() {
    let mut r = Resampler::new(48_000, 16_000, 1);
    let block = vec![0.1f32; 48_000];
    let mut total = 0usize;
    for _ in 0..600 {
        // ten minutes of audio
        let mut out = Vec::new();
        r.process(&block, &mut out);
        total += out.len();
    }
    assert!((total as i64 - 600 * 16_000).abs() < 100);
}
