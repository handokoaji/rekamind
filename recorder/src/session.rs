use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::backend::{Backend, Capture};
use crate::sink::{SourceCtx, SourceState};
use crate::{Source, SAMPLE_RATE};

pub const MARKER: &str = "session.json";

#[derive(Clone, Debug)]
pub struct SourceStatus {
    pub source: Source,
    /// Peak level since the previous call, 0.0..=1.0.
    pub level: f32,
    pub state: SourceState,
    pub seconds: f64,
}

#[derive(Clone, Debug)]
pub struct Status {
    pub elapsed: Duration,
    pub sources: Vec<SourceStatus>,
}

#[derive(Debug)]
pub struct Finished {
    pub dir: PathBuf,
    pub duration: Duration,
    pub files: Vec<(Source, PathBuf)>,
    /// Things the user should hear about (a source that never opened, a disk error...).
    pub warnings: Vec<String>,
}

#[derive(Debug)]
pub enum StartError {
    Io(std::io::Error),
    /// Neither source could be opened. The messages say why, one per source.
    NothingToRecord(Vec<String>),
}

impl std::fmt::Display for StartError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StartError::Io(e) => write!(f, "tidak bisa membuat folder rekaman: {e}"),
            StartError::NothingToRecord(why) => write!(
                f,
                "tidak ada sumber audio yang bisa direkam: {}",
                why.join("; ")
            ),
        }
    }
}
impl std::error::Error for StartError {}

struct Running {
    ctx: Arc<SourceCtx>,
    capture: Option<Box<dyn Capture>>,
}

pub struct Session {
    dir: PathBuf,
    started: Instant,
    running: Vec<Running>,
    warnings: Vec<String>,
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn write_marker(dir: &Path, status: &str, extra: &str) {
    // Best effort: the marker only helps crash recovery, it must never break a recording.
    let _ = fs::write(
        dir.join(MARKER),
        format!(
            "{{\"status\":\"{status}\",\"updated_unix\":{}{extra}}}\n",
            unix_now()
        ),
    );
}

impl Session {
    /// Open the wanted sources and start capturing. Succeeds if at least one source works; a
    /// source that cannot open is reported in `status()` and in `Finished::warnings`.
    pub fn start(
        backend: &dyn Backend,
        dir: &Path,
        want: &[Source],
    ) -> Result<Session, StartError> {
        fs::create_dir_all(dir).map_err(StartError::Io)?;
        write_marker(dir, "recording", "");
        let started = Instant::now();
        let (mut running, mut why) = (Vec::new(), Vec::new());
        for &source in want {
            let ctx =
                SourceCtx::create(source, &dir.join(source.file_name())).map_err(StartError::Io)?;
            match backend.start(ctx.clone()) {
                Ok(capture) => running.push(Running {
                    ctx,
                    capture: Some(capture),
                }),
                Err(msg) => {
                    ctx.set_state(SourceState::Unavailable(msg.clone()));
                    why.push(format!("{}: {msg}", source.label()));
                    running.push(Running { ctx, capture: None });
                }
            }
        }
        if running.iter().all(|r| r.capture.is_none()) {
            write_marker(dir, "failed", "");
            return Err(StartError::NothingToRecord(why));
        }
        Ok(Session {
            dir: dir.to_path_buf(),
            started,
            running,
            warnings: why,
        })
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    pub fn status(&self) -> Status {
        Status {
            elapsed: self.started.elapsed(),
            sources: self
                .running
                .iter()
                .map(|r| SourceStatus {
                    source: r.ctx.source,
                    level: r.ctx.take_level(),
                    state: r.ctx.state(),
                    seconds: r.ctx.samples() as f64 / SAMPLE_RATE as f64,
                })
                .collect(),
        }
    }

    pub fn stop(mut self) -> Finished {
        let duration = self.started.elapsed();
        for r in &self.running {
            r.ctx.begin_stop();
        }
        for r in &mut self.running {
            if let Some(c) = r.capture.take() {
                c.stop();
            }
        }
        // Both files end at the same moment. The capture threads are joined by now, so every source's
        // length is final: pad each one up to the longest (or the wall clock, if that is longer).
        // Measuring only the wall clock would leave a source that wrote one last chunk after it
        // was taken longer than the others -- off by up to a chunk, which misaligns the two channels.
        let wall = (duration.as_secs_f64() * SAMPLE_RATE as f64) as u64;
        let target = self
            .running
            .iter()
            .filter(|r| !matches!(r.ctx.state(), SourceState::Unavailable(_)))
            .map(|r| r.ctx.samples())
            .max()
            .unwrap_or(0)
            .max(wall);
        let mut files = Vec::new();
        for r in &self.running {
            let have = r.ctx.samples();
            if !matches!(r.ctx.state(), SourceState::Unavailable(_)) && have < target {
                r.ctx.push_silence((target - have) as usize);
            }
            if let SourceState::Failed(msg) | SourceState::Unavailable(msg) = r.ctx.state() {
                if !self.warnings.iter().any(|w| w.contains(&msg)) {
                    self.warnings
                        .push(format!("{}: {msg}", r.ctx.source.label()));
                }
            }
            match r.ctx.finish() {
                Ok(0) | Err(_) => {
                    // Nothing usable captured: don't hand an empty file to the uploader.
                    let _ = fs::remove_file(self.dir.join(r.ctx.source.file_name()));
                }
                Ok(_) => files.push((r.ctx.source, self.dir.join(r.ctx.source.file_name()))),
            }
        }
        write_marker(
            &self.dir,
            "complete",
            &format!(",\"duration_ms\":{}", duration.as_millis()),
        );
        Finished {
            dir: self.dir,
            duration,
            files,
            warnings: self.warnings,
        }
    }
}

/// Meeting folders left in the `recording` state by a crash. The app calls this at startup.
pub fn find_unfinished(root: &Path) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(root) else {
        return vec![];
    };
    entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            fs::read_to_string(p.join(MARKER))
                .map(|s| s.contains("\"status\":\"recording\""))
                .unwrap_or(false)
        })
        .collect()
}

/// Repair every WAV in an unfinished meeting folder and mark it complete.
pub fn recover_dir(dir: &Path) -> std::io::Result<Vec<(PathBuf, crate::wav::Recovery)>> {
    let mut out = Vec::new();
    for s in Source::ALL {
        let p = dir.join(s.file_name());
        if p.is_file() {
            out.push((p.clone(), crate::wav::recover(&p)?));
        }
    }
    write_marker(dir, "complete", ",\"recovered\":true");
    Ok(out)
}
