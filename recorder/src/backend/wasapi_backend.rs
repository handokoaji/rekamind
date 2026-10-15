//! Windows: WASAPI shared mode.
//!
//! * Microphone: default capture device. Computer audio: default *render* device opened as a
//!   loopback capture (the `wasapi` crate sets the loopback flag for Render -> Capture).
//! * We ask Windows' audio engine for 16 kHz mono 16-bit directly (`autoconvert`), so on the
//!   normal path this process does no DSP at all. If a driver refuses, we fall back to the
//!   device's own format and convert with our resampler.
//! * Polling, not event-driven: wake ~10x/s per source instead of ~100x/s. Latency is
//!   irrelevant for a recording and fewer wake-ups is what "light" means.
//! * Loopback delivers nothing while the computer is silent, so a wall-clock pacer inserts the
//!   missing silence and keeps both files on one timeline (see `timeline`).
//! * Headset unplugged / default device changed: reopen and carry on.
//!
//! Compiles on every host (`cargo check --target x86_64-pc-windows-gnu`); behaviour on real
//! hardware is verified by running `rekamind-rec record --stats` on Windows.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use wasapi::{
    AudioCaptureClient, AudioClient, DeviceEnumerator, Direction, SampleType, StreamMode,
    WaveFormat,
};

use super::{Backend, Capture};
use crate::resample::Resampler;
use crate::sink::{SourceCtx, SourceState};
use crate::timeline::Pacer;
use crate::{Source, SAMPLE_RATE};

const POLL: Duration = Duration::from_millis(100);
/// 500 ms of buffer against a 100 ms poll: scheduling hiccups don't drop audio.
const BUFFER_HNS: i64 = 5_000_000;
const DEVICE_CHECK_EVERY: Duration = Duration::from_secs(2);

pub struct WasapiBackend;

impl WasapiBackend {
    pub fn new() -> Self {
        Self
    }
}

impl Default for WasapiBackend {
    fn default() -> Self {
        Self::new()
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

enum Convert {
    /// Windows already gave us 16 kHz mono i16.
    Native,
    Soft {
        channels: usize,
        bits: usize,
        float: bool,
        resampler: Resampler,
    },
}

struct Stream {
    client: AudioClient,
    capture: AudioCaptureClient,
    convert: Convert,
    device_id: String,
}

fn direction_for(source: Source) -> Direction {
    match source {
        Source::Mic => Direction::Capture,
        Source::Speaker => Direction::Render, // loopback
    }
}

fn default_device_id(source: Source) -> Result<String, String> {
    let e = DeviceEnumerator::new().map_err(|e| e.to_string())?;
    let d = e
        .get_default_device(&direction_for(source))
        .map_err(|e| e.to_string())?;
    d.get_id().map_err(|e| e.to_string())
}

fn open(source: Source) -> Result<Stream, String> {
    let enumerator =
        DeviceEnumerator::new().map_err(|e| format!("Windows audio tidak tersedia: {e}"))?;
    let device = enumerator
        .get_default_device(&direction_for(source))
        .map_err(|e| match source {
            Source::Mic => format!("tidak ada mikrofon yang aktif ({e})"),
            Source::Speaker => format!("tidak ada perangkat keluaran audio ({e})"),
        })?;
    let device_id = device.get_id().map_err(|e| e.to_string())?;
    let mode = |autoconvert| StreamMode::PollingShared {
        autoconvert,
        buffer_duration_hns: BUFFER_HNS,
    };

    // Preferred: let the Windows audio engine convert to exactly what we need.
    let mut client = device.get_iaudioclient().map_err(|e| e.to_string())?;
    let want = WaveFormat::new(16, 16, &SampleType::Int, SAMPLE_RATE as usize, 1, None);
    let convert = if client
        .initialize_client(&want, &Direction::Capture, &mode(true))
        .is_ok()
    {
        Convert::Native
    } else {
        // An AudioClient cannot be initialised twice: take a fresh one and use the device's own format.
        client = device.get_iaudioclient().map_err(|e| e.to_string())?;
        let mix = client.get_mixformat().map_err(|e| e.to_string())?;
        client
            .initialize_client(&mix, &Direction::Capture, &mode(false))
            .map_err(|e| format!("format audio tidak didukung: {e}"))?;
        let float = matches!(mix.get_subformat(), Ok(SampleType::Float));
        Convert::Soft {
            channels: mix.get_nchannels() as usize,
            bits: mix.get_bitspersample() as usize,
            float,
            resampler: Resampler::new(
                mix.get_samplespersec(),
                SAMPLE_RATE,
                mix.get_nchannels() as usize,
            ),
        }
    };
    let capture = client.get_audiocaptureclient().map_err(|e| e.to_string())?;
    client.start_stream().map_err(|e| e.to_string())?;
    Ok(Stream {
        client,
        capture,
        convert,
        device_id,
    })
}

/// Bytes from the device -> 16 kHz mono i16 appended to `out`.
fn convert_bytes(c: &mut Convert, bytes: &[u8], out: &mut Vec<i16>) {
    match c {
        Convert::Native => out.extend(
            bytes
                .chunks_exact(2)
                .map(|b| i16::from_le_bytes([b[0], b[1]])),
        ),
        Convert::Soft {
            channels,
            bits,
            float,
            resampler,
        } => {
            let mut f: Vec<f32> = Vec::with_capacity(bytes.len() / 2);
            match (*float, *bits) {
                (true, 32) => f.extend(
                    bytes
                        .chunks_exact(4)
                        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]])),
                ),
                (false, 16) => f.extend(
                    bytes
                        .chunks_exact(2)
                        .map(|b| i16::from_le_bytes([b[0], b[1]]) as f32 / 32768.0),
                ),
                (false, 32) => f.extend(bytes.chunks_exact(4).map(|b| {
                    i32::from_le_bytes([b[0], b[1], b[2], b[3]]) as f32 / 2_147_483_648.0
                })),
                (false, 24) => f.extend(bytes.chunks_exact(3).map(|b| {
                    (i32::from_le_bytes([0, b[0], b[1], b[2]]) >> 8) as f32 / 8_388_608.0
                })),
                _ => return, // unknown layout: drop rather than write noise
            }
            let whole = f.len() - f.len() % *channels;
            resampler.process(&f[..whole], out);
        }
    }
}

enum End {
    Stopped,
    DeviceLost,
}

/// Upper bound on packets taken in one poll (~10 ms each, so ~10 s): a stuck driver that keeps
/// reporting a packet must not wedge the capture thread.
const MAX_PACKETS_PER_POLL: usize = 1000;

/// Read every packet that is ready. `wasapi`'s `read_from_device_to_deque` takes exactly ONE
/// packet (~10 ms) per call, so reading once per 100 ms poll kept ~10% of the audio and let the
/// pacer pad the rest with zeros -- choppy audio that the VAD then discarded entirely.
fn drain_packets<E>(
    mut next_size: impl FnMut() -> Result<Option<u32>, E>,
    mut read_one: impl FnMut() -> Result<(), E>,
) -> Result<usize, E> {
    let mut n = 0;
    while n < MAX_PACKETS_PER_POLL {
        match next_size()? {
            Some(frames) if frames > 0 => read_one()?,
            _ => break,
        }
        n += 1;
    }
    Ok(n)
}

fn run_stream(ctx: &SourceCtx, stream: &mut Stream, stop: &AtomicBool, pacer: &mut Pacer) -> End {
    let mut queue: VecDeque<u8> = VecDeque::with_capacity(64 * 1024);
    let mut bytes: Vec<u8> = Vec::new();
    let mut samples: Vec<i16> = Vec::with_capacity(8192);
    let mut last_check = Instant::now();
    while !stop.load(Ordering::Relaxed) {
        thread::sleep(POLL);
        let drained = drain_packets(
            || stream.capture.get_next_packet_size(),
            || stream.capture.read_from_device_to_deque(&mut queue).map(|_| ()),
        );
        if drained.is_err() {
            return End::DeviceLost; // any read failure here means the device went away
        }
        samples.clear();
        if !queue.is_empty() {
            bytes.clear();
            bytes.extend(queue.drain(..));
            convert_bytes(&mut stream.convert, &bytes, &mut samples);
        }
        // Silence between packets (an idle loopback) -> insert it so the timeline stays true.
        let gap = pacer.gap(Instant::now()).saturating_sub(samples.len());
        if gap > 0 {
            ctx.push_silence(gap);
            pacer.wrote(gap);
        }
        if !samples.is_empty() {
            ctx.push(&samples);
            pacer.wrote(samples.len());
        }
        if last_check.elapsed() >= DEVICE_CHECK_EVERY {
            last_check = Instant::now();
            // The user switched the default device (e.g. plugged in a headset): follow them.
            if let Ok(id) = default_device_id(ctx.source) {
                if id != stream.device_id {
                    return End::DeviceLost; // default device changed
                }
            }
        }
    }
    End::Stopped
}

impl Backend for WasapiBackend {
    fn start(&self, ctx: Arc<SourceCtx>) -> Result<Box<dyn Capture>, String> {
        let stop = Arc::new(AtomicBool::new(false));
        let (tx, rx) = mpsc::channel::<Result<(), String>>();
        let flag = stop.clone();
        let thread = thread::Builder::new()
            .name(format!("capture-{}", ctx.source.api_name()))
            .spawn(move || {
                let _ = wasapi::initialize_mta().ok(); // COM must be initialised on this thread
                let mut first = Some(tx);
                let mut pacer = Pacer::new(Instant::now(), SAMPLE_RATE);
                while !flag.load(Ordering::Relaxed) {
                    match open(ctx.source) {
                        Ok(mut stream) => {
                            if let Some(tx) = first.take() {
                                let _ = tx.send(Ok(()));
                            } else {
                                ctx.set_state(SourceState::Recording);
                            }
                            let end = run_stream(&ctx, &mut stream, &flag, &mut pacer);
                            let _ = stream.client.stop_stream();
                            if let End::Stopped = end {
                                break;
                            }
                            ctx.set_state(SourceState::Reconnecting);
                        }
                        Err(e) => {
                            if let Some(tx) = first.take() {
                                let _ = tx.send(Err(e)); // could not even start: let the session say why
                                return;
                            }
                            ctx.set_state(SourceState::Reconnecting);
                        }
                    }
                    // Back off, but keep the timeline moving while we are blind.
                    let until = Instant::now() + Duration::from_secs(1);
                    while Instant::now() < until && !flag.load(Ordering::Relaxed) {
                        thread::sleep(Duration::from_millis(100));
                    }
                    let gap = pacer.gap(Instant::now());
                    if gap > 0 {
                        ctx.push_silence(gap);
                        pacer.wrote(gap);
                    }
                }
            })
            .map_err(|e| e.to_string())?;
        match rx.recv_timeout(Duration::from_secs(8)) {
            Ok(Ok(())) => Ok(Box::new(Running {
                stop,
                thread: Some(thread),
            })),
            Ok(Err(e)) => {
                let _ = thread.join();
                Err(e)
            }
            Err(_) => {
                stop.store(true, Ordering::Relaxed);
                Err("perangkat audio tidak merespons".into())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `packets` ready frames, then idle (0), like a loopback that has caught up.
    fn run(packets: usize) -> (usize, usize) {
        let left = std::cell::Cell::new(packets);
        let read = std::cell::Cell::new(0);
        let n = drain_packets::<()>(
            || Ok(Some(if left.get() > 0 { 160 } else { 0 })),
            || {
                left.set(left.get() - 1);
                read.set(read.get() + 1);
                Ok(())
            },
        )
        .unwrap();
        (n, read.get())
    }

    #[test]
    fn drains_every_queued_packet_not_just_one() {
        // 100 ms poll over a 10 ms packet cadence leaves ~10 packets waiting.
        assert_eq!(run(10), (10, 10));
    }

    #[test]
    fn idle_loopback_reads_nothing() {
        assert_eq!(run(0), (0, 0));
    }

    #[test]
    fn stuck_driver_is_bounded() {
        let n = drain_packets::<()>(|| Ok(Some(160)), || Ok(())).unwrap();
        assert_eq!(n, MAX_PACKETS_PER_POLL);
    }

    #[test]
    fn exclusive_mode_none_does_not_spin() {
        let n = drain_packets::<()>(|| Ok(None), || Ok(())).unwrap();
        assert_eq!(n, 0);
    }

    #[test]
    fn read_error_is_propagated() {
        assert!(drain_packets(|| Ok(Some(160)), || Err("gone")).is_err());
    }
}
