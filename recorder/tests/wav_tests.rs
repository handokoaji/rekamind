mod common;
use common::read_wav;
use rekamind_recorder::wav::{recover, WavWriter};

fn tone(n: usize) -> Vec<i16> {
    (0..n)
        .map(|i| ((i as f32 * 0.05).sin() * 10000.0) as i16)
        .collect()
}

#[test]
fn writes_a_strictly_valid_wav() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("a.wav");
    let mut w = WavWriter::create(&p, 16000).unwrap();
    w.write_samples(&tone(16000)).unwrap();
    assert_eq!(w.finish().unwrap(), 16000);
    let wav = read_wav(&p);
    assert_eq!((wav.rate, wav.channels, wav.bits), (16000, 1, 16));
    assert_eq!(wav.samples.len(), 16000);
    assert_eq!(wav.declared_data as u64, wav.actual_data);
}

#[test]
fn a_crash_loses_at_most_the_checkpoint_window_and_recover_restores_the_rest() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("a.wav");
    let mut w = WavWriter::create(&p, 16000).unwrap();
    for _ in 0..7 {
        w.write_samples(&tone(16000)).unwrap(); // 7 s, in 1 s pieces
    }
    // "Crash": snapshot the file exactly as the OS has it, without finish()/flush().
    let crashed = d.path().join("crashed.wav");
    std::fs::copy(&p, &crashed).unwrap();
    drop(w);

    let file_len = std::fs::metadata(&crashed).unwrap().len();
    assert!(
        file_len >= 44 + 2 * 32000,
        "at least the checkpointed seconds are on disk, got {file_len} bytes"
    );
    let rec = recover(&crashed).unwrap();
    assert!(
        rec.samples >= 6 * 16000 - 32000 && rec.samples <= 7 * 16000,
        "recovered {} samples",
        rec.samples
    );
    let wav = read_wav(&crashed); // strict: header must now be consistent with the data
    assert_eq!(wav.samples.len() as u64, rec.samples);
}

#[test]
fn recover_drops_a_torn_final_sample_and_is_idempotent() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("a.wav");
    let mut w = WavWriter::create(&p, 16000).unwrap();
    w.write_samples(&tone(1000)).unwrap();
    w.finish().unwrap();
    let mut f = std::fs::OpenOptions::new().append(true).open(&p).unwrap();
    std::io::Write::write_all(&mut f, &[0x7F]).unwrap(); // half a sample, as if killed mid-write
    drop(f);
    let first = recover(&p).unwrap();
    assert!(first.repaired && first.samples == 1000);
    let second = recover(&p).unwrap();
    assert!(!second.repaired, "a healthy file is left alone");
    assert_eq!(read_wav(&p).samples.len(), 1000);
}

#[test]
fn recover_refuses_things_that_are_not_wav() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("x.wav");
    std::fs::write(
        &p,
        b"this is not audio at all, definitely longer than a header......",
    )
    .unwrap();
    assert!(recover(&p).is_err());
    std::fs::write(&p, b"tiny").unwrap();
    assert!(recover(&p).is_err());
}
