//! Sending a finished recording to the backend, with byte-level progress and retries.
//! Shared by the CLI and the desktop shell so both behave identically.

use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::api::Client;
use crate::Source;

#[derive(Clone, Debug, Default)]
pub struct Meta {
    pub title: String,
    pub language: String,
    pub local_user_name: Option<String>,
    pub process: bool,
}

/// What is happening, for a progress UI.
#[derive(Clone, Debug, PartialEq)]
pub struct Progress {
    pub step: &'static str,
    /// 0.0 ..= 1.0 over the whole upload (bytes dominate; small steps are rounding noise).
    pub fraction: f32,
}

struct Counting<'a, F: FnMut(u64)> {
    inner: File,
    on_bytes: &'a mut F,
}

impl<F: FnMut(u64)> Read for Counting<'_, F> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let n = self.inner.read(buf)?;
        (self.on_bytes)(n as u64);
        Ok(n)
    }
}

const RETRIES: u32 = 3;

/// The meeting exists on the server with all its audio. Processing is a separate, optional step that
/// can fail for reasons the recording does not care about (engines not installed yet, no API key).
pub struct Uploaded {
    pub id: String,
    /// Why the automatic "process" request was refused, if it was. The upload itself still succeeded.
    pub not_processed: Option<String>,
}

/// Create the meeting, upload every file, finish, optionally process. Returns the meeting id.
/// `sleep` is injectable so tests don't wait out the backoff.
pub fn upload_meeting(
    client: &Client,
    files: &[(Source, PathBuf)],
    meta: &Meta,
    mut progress: impl FnMut(Progress),
    sleep: impl Fn(Duration),
) -> Result<Uploaded, String> {
    let total: u64 = files
        .iter()
        .map(|(_, p)| std::fs::metadata(p).map(|m| m.len()).unwrap_or(0))
        .sum::<u64>()
        .max(1);
    progress(Progress {
        step: "menghubungi server",
        fraction: 0.0,
    });
    client.health().map_err(|e| e.to_string())?;
    let id = client
        .create_meeting(&meta.title, &meta.language, meta.local_user_name.as_deref())
        .map_err(|e| e.to_string())?;

    let mut sent: u64 = 0;
    for (source, path) in files {
        let mut last_err = String::new();
        let base = sent;
        for attempt in 0..RETRIES {
            if attempt > 0 {
                sleep(Duration::from_secs(2 << attempt));
            }
            sent = base; // a retry restarts this file; progress must not overshoot
            let mut counted = 0u64;
            let step = match source {
                Source::Mic => "mengunggah mikrofon",
                Source::Speaker => "mengunggah audio komputer",
            };
            let result = {
                let mut on_bytes = |n: u64| {
                    counted += n;
                    progress(Progress {
                        step,
                        fraction: ((base + counted) as f32 / total as f32 * 0.97).min(0.97),
                    });
                };
                client.upload_reader(
                    &mut Counting {
                        inner: open(path)?,
                        on_bytes: &mut on_bytes,
                    },
                    std::fs::metadata(path).map(|m| m.len()).unwrap_or(0),
                    &id,
                    *source,
                )
            };
            match result {
                Ok(()) => {
                    sent = base + counted;
                    last_err.clear();
                    break;
                }
                Err(e) => last_err = e.to_string(),
            }
        }
        if !last_err.is_empty() {
            return Err(format!("unggahan {} gagal: {last_err}", source.label()));
        }
    }
    progress(Progress {
        step: "menyelesaikan",
        fraction: 0.98,
    });
    client.finish(&id).map_err(|e| e.to_string())?;
    let mut not_processed = None;
    if meta.process {
        progress(Progress {
            step: "memulai pemrosesan",
            fraction: 0.99,
        });
        // The audio is safely on the server at this point; failing here must not look like a failed upload.
        not_processed = client.process(&id).err().map(|e| e.to_string());
    }
    progress(Progress {
        step: "selesai",
        fraction: 1.0,
    });
    Ok(Uploaded { id, not_processed })
}

fn open(path: &Path) -> Result<File, String> {
    File::open(path).map_err(|e| format!("{}: {e}", path.display()))
}
