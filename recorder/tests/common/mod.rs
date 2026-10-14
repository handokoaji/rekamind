#![allow(dead_code)]
use std::path::Path;

pub struct Wav {
    pub rate: u32,
    pub channels: u16,
    pub bits: u16,
    pub declared_data: u32,
    pub actual_data: u64,
    pub samples: Vec<i16>,
}

/// Strict reader: fails the test if the file is not a well-formed 16-bit mono PCM WAV.
pub fn read_wav(path: &Path) -> Wav {
    let b = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    assert!(b.len() >= 44, "too short for WAV");
    assert_eq!(&b[0..4], b"RIFF");
    assert_eq!(&b[8..16], b"WAVEfmt ");
    assert_eq!(&b[36..40], b"data");
    let u32at = |o: usize| u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]);
    let u16at = |o: usize| u16::from_le_bytes([b[o], b[o + 1]]);
    assert_eq!(u16at(20), 1, "PCM");
    let declared = u32at(40);
    assert_eq!(u32at(4), 36 + declared, "RIFF size must match data size");
    let samples = b[44..]
        .chunks_exact(2)
        .map(|c| i16::from_le_bytes([c[0], c[1]]))
        .collect();
    Wav {
        rate: u32at(24),
        channels: u16at(22),
        bits: u16at(34),
        declared_data: declared,
        actual_data: b.len() as u64 - 44,
        samples,
    }
}

pub fn peak(s: &[i16]) -> i16 {
    s.iter()
        .map(|v| v.unsigned_abs())
        .max()
        .unwrap_or(0)
        .min(32767) as i16
}
