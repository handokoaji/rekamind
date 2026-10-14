//! A WAV writer that survives being killed.
//!
//! The header's size fields are rewritten every [`CHECKPOINT_SECONDS`], so a crash, a power
//! cut or a force-quit loses at most that much audio rather than the whole meeting. After an
//! unclean exit, [`recover`] repairs the header from the file's real length.

use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::Path;

pub const HEADER_LEN: u64 = 44;
pub const CHECKPOINT_SECONDS: u64 = 2;

fn header(rate: u32, data_bytes: u32) -> [u8; 44] {
    let mut h = [0u8; 44];
    h[0..4].copy_from_slice(b"RIFF");
    h[4..8].copy_from_slice(&(36u32.saturating_add(data_bytes)).to_le_bytes());
    h[8..16].copy_from_slice(b"WAVEfmt ");
    h[16..20].copy_from_slice(&16u32.to_le_bytes());
    h[20..22].copy_from_slice(&1u16.to_le_bytes()); // PCM
    h[22..24].copy_from_slice(&1u16.to_le_bytes()); // mono
    h[24..28].copy_from_slice(&rate.to_le_bytes());
    h[28..32].copy_from_slice(&(rate * 2).to_le_bytes());
    h[32..34].copy_from_slice(&2u16.to_le_bytes());
    h[34..36].copy_from_slice(&16u16.to_le_bytes());
    h[36..40].copy_from_slice(b"data");
    h[40..44].copy_from_slice(&data_bytes.to_le_bytes());
    h
}

pub struct WavWriter {
    out: BufWriter<File>,
    rate: u32,
    data_bytes: u64,
    since_checkpoint: u64,
}

impl WavWriter {
    pub fn create(path: &Path, rate: u32) -> io::Result<Self> {
        let mut f = File::create(path)?;
        f.write_all(&header(rate, 0))?;
        Ok(Self {
            out: BufWriter::with_capacity(64 * 1024, f),
            rate,
            data_bytes: 0,
            since_checkpoint: 0,
        })
    }

    pub fn samples(&self) -> u64 {
        self.data_bytes / 2
    }

    pub fn write_samples(&mut self, samples: &[i16]) -> io::Result<()> {
        // One allocation-free pass: little-endian i16 straight into the buffered writer.
        for s in samples {
            self.out.write_all(&s.to_le_bytes())?;
        }
        let n = samples.len() as u64 * 2;
        self.data_bytes += n;
        self.since_checkpoint += n;
        if self.since_checkpoint >= CHECKPOINT_SECONDS * self.rate as u64 * 2 {
            self.checkpoint()?;
        }
        Ok(())
    }

    /// Flush to disk and make the header describe everything written so far.
    pub fn checkpoint(&mut self) -> io::Result<()> {
        self.out.flush()?;
        let f = self.out.get_mut();
        let data = self.data_bytes.min(u32::MAX as u64) as u32;
        f.seek(SeekFrom::Start(4))?;
        f.write_all(&(36u32.saturating_add(data)).to_le_bytes())?;
        f.seek(SeekFrom::Start(40))?;
        f.write_all(&data.to_le_bytes())?;
        f.seek(SeekFrom::End(0))?;
        self.since_checkpoint = 0;
        Ok(())
    }

    pub fn finish(mut self) -> io::Result<u64> {
        self.checkpoint()?;
        self.out.get_mut().sync_all()?;
        Ok(self.samples())
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Recovery {
    pub samples: u64,
    /// True when the header disagreed with the file (i.e. the recording had not been closed cleanly).
    pub repaired: bool,
}

/// Repair a WAV whose writer was killed: trust the file's length, not the header.
pub fn recover(path: &Path) -> io::Result<Recovery> {
    let mut f = OpenOptions::new().read(true).write(true).open(path)?;
    let len = f.metadata()?.len();
    if len < HEADER_LEN {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "file terlalu pendek untuk WAV",
        ));
    }
    let mut head = [0u8; 44];
    f.read_exact(&mut head)?;
    if &head[0..4] != b"RIFF" || &head[8..12] != b"WAVE" {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "bukan file WAV"));
    }
    let actual = ((len - HEADER_LEN) & !1).min(u32::MAX as u64) as u32; // drop a torn final sample
    let declared = u32::from_le_bytes([head[40], head[41], head[42], head[43]]);
    // A stray half-sample at the end also counts: it must be trimmed even if the header agrees.
    let repaired = declared != actual || len != HEADER_LEN + actual as u64;
    if repaired {
        f.seek(SeekFrom::Start(4))?;
        f.write_all(&36u32.saturating_add(actual).to_le_bytes())?;
        f.seek(SeekFrom::Start(40))?;
        f.write_all(&actual.to_le_bytes())?;
        f.set_len(HEADER_LEN + actual as u64)?;
        f.sync_all()?;
    }
    Ok(Recovery {
        samples: actual as u64 / 2,
        repaired,
    })
}
