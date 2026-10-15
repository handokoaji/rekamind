# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]


### Changed
- Engine install is observable and more robust: a diagnostics block (pip version, package sources/proxies with credentials masked, host reachability), a progress line every few seconds with speed, a warning when a download stalls, longer timeouts/retries, and resumable downloads on pip >= 25.1. Arguments for CPU/NVIDIA installs are otherwise unchanged.

### Added
- AMD GPU (integrated Radeon 680M/780M/860M and other Vulkan GPUs) transcription through whisper.cpp built with Vulkan: engine kind `vulkan` (*Pasang untuk GPU AMD (Vulkan)*), `whisper_device=vulkan`, program built by CI (`engine-assets` workflow) and downloaded with SHA-256 verification, ggml models from Hugging Face. **Experimental: tested with a fake program only, not verified on real hardware.**
- Intel GPU (integrated Arc/Iris Xe, e.g. Core Ultra 7 155H) transcription through OpenVINO: new engine kind `openvino` in the engine pack (*Pasang untuk Intel GPU*), `whisper_device=intel`, GPU detection to recommend it, falls back to the CPU when the GPU cannot load the model. **Experimental: unit-tested with fakes only, not verified on real hardware.**

## [0.4.0-beta.1] - 2026-10-15

First release of the v2 generation (pre-release, for testing). Replaces the v1 (Tkinter) app; not compatible with it.

### Added
- Rust recorder (microphone + system audio) and Tauri desktop app for Windows and Linux, with the local backend bundled.
- FastAPI backend: job queue, transcription (faster-whisper), optional speaker separation, summary/task extraction via an OpenAI-compatible LLM.
- React web interface: meetings, summary, tasks, transcript, speakers, settings.
- Word/Markdown/JSON export; GitHub, GitLab and signed-webhook integrations; time zone setting (default WIB).
- Google sign-in (OIDC + PKCE) and per-user ownership for the shared server; Docker Compose.
- On-demand transcription engine install from the app (CPU or NVIDIA).
- English (default) and Indonesian documentation.

### Planned (not implemented)
- Intel GPU (incl. integrated) and AMD GPU (incl. integrated) acceleration; more interface languages; output-language choice.

### Known issues
- Installers are unsigned; Linux desktop untested on real hardware; AMD/Intel GPUs unsupported (CPU only) and untested. See the release notes.

## [0.3.0] - 2026-09-23

### Added

- **Full transcript in the MoM docx**: `mom.docx` now ends with a
  "Transkrip Lengkap" section listing every final transcript segment as
  `[HH:MM:SS - HH:MM:SS] Speaker: text` (offsets from the start of the
  recording). Backed by the new `repo.get_final_transcript_timed` and
  `app/timeutil.py::format_transcript_lines`. Only docx files generated from
  now on include it -- re-run Ringkasan on an older meeting to regenerate its
  docx with the transcript.

## [0.2.0] - 2026-08-06

### Added

- **Impor Rekaman**: add a meeting straight from an uploaded audio/video file
  (`app/ui/controller.py::RecorderController.import_meeting`), skipping
  Mulai Rekam/Stop Rekam entirely. ffmpeg extracts the audio track to a
  16kHz mono `speaker.wav` (so it's diarized into per-speaker labels like
  any recorded meeting); `mic.wav` is a near-silent placeholder since an
  uploaded file has no separate mic channel. Lands in Riwayat with status
  "recorded", ready for Transkrip/Ringkasan immediately.
- **Cross-device processing via sync**: Transkrip/Ringkasan/Coba Lagi now
  work on a meeting recorded by another device, not just this device's own.
  `RecorderController._ensure_audio_files` fetches `mic.wav`/`speaker.wav`
  from MinIO on demand (same lazy-download pattern `ensure_docx_available`
  already used for `mom.docx`) before processing. `push()`/`pull()`
  (`app/sync/minio_client.py`) now round-trip results both ways:
  - `push()` also pushes a foreign meeting's manifest (and its `mom.docx`)
    back to the *original owner's* MinIO prefix once this device has
    actually transcribed/summarized it, not just this device's own meetings.
  - `pull()` updates an already-known meeting in place when the remote
    manifest has moved further along the status state machine (never
    backward, so an in-flight local action is never clobbered by a stale
    manifest) -- including manifests written to *this device's own* prefix
    by someone else who processed one of its meetings, which used to be
    skipped outright.
  - `ensure_docx_available` no longer assumes "my own meeting" implies "docx
    already on my disk" -- it can now be fetched from MinIO regardless of
    who authored it.

### Fixed

- `app/__init__.py::__version__` was still `0.1.0`; the v0.1.1 release only
  bumped `pyproject.toml`. Both now agree.

## [0.1.1] - 2026-08-03

Validated the Intel Core Ultra 7 155H (CPU/iGPU/NPU) path on real hardware.

### Added

- `LIVE_ASR_BACKEND_OVERRIDE` setting: lets the live-preview pipeline use a
  different ASR backend than the batch pass, independent of
  `ASR_BACKEND_OVERRIDE`. Empty (default) keeps today's behavior — live
  follows whatever backend batch is using.

### Changed

- `OpenVinoWhisperBackend` (Intel iGPU) now chunks audio into
  `MAX_TRANSCRIBE_SECONDS` (30s) windows instead of hard-raising
  `NotImplementedError` past the first one — the batch pass (Transkrip) can
  now actually be used with `ASR_BACKEND_OVERRIDE=openvino` on a real,
  full-length meeting recording, which it could not before.

### Removed

- An NPU ASR backend (`openvino-genai`'s `WhisperPipeline`, process-isolated
  the same way `ProcessIsolatedDiarizer` is) was built and evaluated on the
  Core Ultra 7 155H's NPU, then removed. Root cause: the NPU compiler only
  supports greedy decoding — beam search fails outright with a static-shape
  tensor error — and greedy decoding on real Indonesian speech reliably
  degenerated into repeated phrases or drifted into English, confirmed via
  side-by-side transcription of the same recording (iGPU: correct, stable
  Indonesian; NPU: garbled English), even after tuning
  `repetition_penalty`/`min_new_tokens`. Not worth keeping without an
  upstream NPU decoding fix.

## [0.1.0] - 2026-08-02

First tagged release. Validated end-to-end on one machine (AMD Ryzen 5 5600G +
NVIDIA GTX 1080 Ti, CUDA path). The Intel Core Ultra 7 155H (CPU/OpenVINO) path
is implemented and unit-tested but not yet run on real hardware.

### Added

- Simultaneous mic + system-audio (WASAPI loopback) capture via `pyaudiowpatch`.
- Near-real-time live transcription and speaker-diarization preview while
  recording, deliberately decoupled from the authoritative post-meeting pass:
  "Mulai Rekam"/"Stop Rekam" only capture audio; Transkrip/Ringkasan are
  separate, manually-triggered actions per meeting from the history tab.
- Full-recording batch transcription (faster-whisper `large-v3`) and
  re-diarization (pyannote `speaker-diarization-3.1`) after the meeting, fully
  replacing the provisional live preview.
- Bahasa Indonesia Minutes-of-Meeting generation via Groq, exported to `.docx`.
- Automatic hardware backend detection (CUDA / CPU via ctranslate2), with a
  clear fatal-error dialog instead of a silent slow fallback on hardware that
  supports neither.
- SQLite (zero-config) and Postgres (multi-seat) storage backends, selected
  via `STORAGE_BACKEND`.
- Multi-device identity (`device_id`/`device_label`, defaulting to hostname in
  dev mode) stamped on every recorded meeting, so a shared history view can
  tell "your meetings" from a colleague's.
- Optional MinIO-based sync: `push()` uploads a manifest and files for
  locally-owned meetings; `pull()` materializes other devices' manifests into
  local history; `mom.docx` downloads on demand rather than eagerly.
- First-run setup wizard for packaged installs (storage backend, API keys,
  MinIO, device label), writing to `%LOCALAPPDATA%\MeetingRecorder\config.json`.
- Meeting lifecycle recovery — an app crash mid-transcription or
  mid-summarization resets the meeting to retryable on next launch instead of
  leaving it stuck.
- System tray icon, a startup update-availability check, and an install-guide
  dialog when ffmpeg is missing from PATH.
- Windows installer build pipeline (PyInstaller + Inno Setup) and a GitHub
  Actions workflow that runs the test suite, builds the installer, and
  attaches it to tagged releases.

### Changed

- Rebranded from "Meeting Recorder" to Rekamind (packaging artifacts, UI
  strings, license). The on-disk `%LOCALAPPDATA%\MeetingRecorder\` data
  directory is deliberately unchanged, to avoid orphaning existing installs'
  local data.
- Live diarization re-diarizes only the trailing ~5 minutes of the growing
  speaker WAV per tick instead of the whole file, keeping tick time bounded
  regardless of meeting length.
- ASR and diarization backends (`FasterWhisperBackend`, `OpenVinoWhisperBackend`,
  `Diarizer`, `ProcessIsolatedDiarizer`) now import lazily, inside the
  functions that use them, instead of at module load. Measured effect: idle
  memory after `import app.main` dropped from ~924MB to ~99MB, and import time
  from ~7-9s to ~1s.
- Batch models (`large-v3` + pyannote, loaded on the first Transkrip/Ringkasan
  click) now unload automatically after 15 minutes of inactivity instead of
  staying resident for the rest of the app run.
- The live transcriber on CUDA now uses `int8` instead of `float32`, matching
  the batch transcriber's precision.
- The live-preview diarizer's worker process is torn down whenever a
  recording stops, instead of staying resident between meetings holding a
  full pyannote model.
- `OpenVinoWhisperBackend` (Intel GPU/NPU) is no longer auto-selected by
  hardware detection: it has no chunking loop and hard-fails past 30 seconds
  of audio rather than silently truncating a meeting. Still reachable via
  `ASR_BACKEND_OVERRIDE=openvino` for development; a properly chunked
  implementation is pending validation on real Intel hardware.

### Fixed

- CUDA-enabled `torch` is now a documented, explicit install step (`README.md`,
  CI) — a plain `pip install -e .` previously produced a build with zero CUDA
  support, silently, because PyPI's default `torch` wheel has none and
  `pyproject.toml` cannot pin a per-package index URL.
- The diarizer no longer crashes the entire Transkrip/live-diarize action with
  an uncaught `Torch not compiled with CUDA enabled` when ctranslate2 reports
  CUDA available but the installed `torch` wheel doesn't have it.
- `mom.docx` is written to the meeting's actual recording directory instead of
  a stale path, fixing sync, download, and delete for exported documents.
- The log directory, and now the OpenVINO model-conversion cache, default to
  `%LOCALAPPDATA%\MeetingRecorder\` instead of the process's current working
  directory, which can be anywhere in a packaged install.
- Deleted meetings no longer get resurrected by a later sync pull — a
  soft-delete tombstone (`Meeting.deleted_at`) was added.
- "Pengaturan" and startup DB-error recovery no longer silently no-op in dev
  mode.
- A non-numeric Postgres port no longer crashes the setup wizard uncaught.
- A live-diarize worker leak that could drive RAM usage past 20GB over a long
  meeting was fixed by capping the re-diarization window and, later, tearing
  the worker down as soon as recording stops.
- Summarization now chunks long transcripts to stay under Groq's per-minute
  token limit, pacing requests and merging chunk results mechanically instead
  of failing or truncating on long meetings.
- Assorted background-thread-safety fixes: history actions, Mulai
  Rekam/Stop Rekam, tray icon show/quit, and Unduh Docx all marshal UI
  updates through the thread-safe `push_live_event` queue instead of
  touching Tk widgets off the main thread.

### Security

- `pull()` and `download_file()` validate the `device_id`/`meeting_dir`
  segments of remote MinIO object names against a strict charset and resolve
  the local path against the recordings root before writing anything, closing
  a path-traversal vector where a compromised or malicious peer device
  sharing the same bucket could otherwise write outside the intended
  directory.

[0.1.0]: https://github.com/handokoaji/rekamind/releases/tag/v0.1.0
[0.4.0-beta.1]: https://github.com/handokoaji/rekamind/releases/tag/v0.4.0-beta.1
