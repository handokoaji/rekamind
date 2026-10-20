# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **The meeting list shows the newest 10 and has real pagination** (it was 50 at a time with a "show more" button). Previous / next with "Halaman 2 dari 3" and "11–20 dari 23 rapat"; each page is a browser history entry (`?hal=2`), a new search or filter starts again from page 1, and landing past the end after deletions steps back to the last page. The server reports the total in an `X-Total-Count` header (same filters as the list; the body is still a plain list, so existing API clients are unaffected) and exposes it to the desktop app. A server that does not send it still pages (next is offered while a page comes back full). The Task tab is not paged yet.
- **Light / dark setting** (Settings > Tampilan): "Ikuti sistem" (the default), "Terang" or "Gelap". Until now the colours only followed the system. The choice is kept on the device and applied before the page is painted (`public/theme-init.js`, a separate file because the content security policy allows scripts only from the app itself), so a dark choice does not flash white first. Works the same in the web page and the desktop app.
- **Credit for the author, kept quiet.** A small "Tentang Rekamind" card at the end of Settings (version, licence, "made by Rochmad Handoko Aji" with an Instagram icon, source code, report an issue, and one sentence about supporting the project with a heart icon for GitHub Sponsors and a cup for Saweria; the icons carry a tooltip and an accessible name), one muted line at the foot of every page, and one line on the sign-in screen. Text and plain links only: no buttons, no pop-ups, nothing in the recording or meeting views. The same component serves the desktop app and the web page. In the desktop app a link click is handed to the system browser by a new `open_external` command that opens only the author's pages (a click would otherwise replace the app with that site). Also: the installer's publisher and copyright, author fields in the package metadata, the API's contact and licence, and the copyright holder's full name in the READMEs.
- **"Poin penting" (key points) in the summary**, apart from "Keputusan" (decisions) and "Jalannya rapat" (the time-ordered detail): the headline is the key points and the decisions, the timeline is the detail below them. New `key_points` field (migration `0005`, existing summaries get an empty list), shown on the summary tab and written to the JSON, Markdown and Word exports. A section with nothing in it now says so ("Tidak ada poin penting yang tercatat.") instead of disappearing, which looked like a missing feature.
- **Slow model downloads are cut off and retried** (`hfguard.py`, setting `REKAMIND_HF_MIN_MBPS`, default 0.5, 0 = off). Hugging Face serves model files from a CDN host that resolves to about ten addresses; on a real server one of them answered at 0.1 MB/s while the rest gave about 27 MB/s. `huggingface_hub` only times out when no byte arrives for ten seconds, and a slow node keeps trickling bytes, so the connection stayed on it: the first Whisper download, and later a 26 MB pyannote file (10 MiB in 100 s, then nothing for minutes), never finished and the job hung in `diarizing`. A response of 20 MB or more whose rate stays under the minimum for 10 s (after a 12 s grace) now raises a timeout, `huggingface_hub` resumes it, and the dropped connection means the retry usually lands on a healthy node. Covers every model download (Whisper and pyannote) that goes through plain HTTP.

### Changed
- **Decisions are now defined in the prompt.** Tasks had a long list of rules, "decisions" had none (it was only a field name), and the model sometimes put a constraint ("the audit deadline is 30 October") in the list. A decision is now an agreement, conclusion or direction taken even when nobody says "we decide" ("ok we go with vendor A", "so the launch moves to Monday"), and a proposal nobody accepted is not one. On one made-up transcript with the real model (Groq), the old prompt listed the audit deadline as a decision in 2 of 2 runs; the new wording did in 1 of 5 runs, and never listed the rejected proposal. The final wording also caught the unanswered question ("who holds the vendor contract") in 2 of 3 runs. Key points are told not to repeat decisions and tasks, but the model still repeats them now and then. One invented transcript is a weak test: judge it on real meetings.
- `HF_HUB_DISABLE_XET=1` stays, but for a different reason than stated in beta.6: the guard can only watch plain HTTP downloads. The beta.6 note blamed the Xet downloader; that was not proven, and the slow CDN node above explains the stalls without it.

### Measured
- Speaker separation on a real GPU server (RTX 4060 Ti, 16 GB, image `0.4.0-beta.6-cuda-diarize`), one short recording: pyannote ran on the GPU and split the computer's audio into two voices (`SPEAKER_00` 92 segments, `SPEAKER_01` 38; the microphone stays `ME`). VRAM peaked at 8,534 MiB (idle 2,601; Whisper about +4.1 GB, pyannote about +1.8 GB more) and returned to 2,824 MiB when the queue emptied.

### Fixed
- **A daily LLM quota now fails at once with a clear message.** The summary service (Groq's free tier: 200,000 tokens a day) can run out; the request used to be retried four times with 60-second waits, ending after about four minutes with a raw JSON error. A per-day quota, or any wait over two minutes, now stops immediately with "Kuota layanan LLM habis ... Coba lagi sekitar 21m3s lagi"; short per-minute limits are still waited out. The transcript is kept and "Buat ulang ringkasan" retries the summary.
- **The tokens a summary really cost are logged** (`summary used N tokens (in, out) in K call(s)`), because providers meter them per day and a two-hour meeting is many calls.
- **The desktop app did not show the Google profile picture** (the web page served by the server did). The app's content security policy only allowed images from itself, so the picture at `lh3.googleusercontent.com` was blocked; `img-src` now allows `https:`, the same as the server's own policy. The only remote image the interface shows is that picture.
- **The in-app update notice never appeared when GitHub's API refused the request.** The API allows 60 anonymous calls an hour per IP address, and a campus or an office shares one address, so the quota is easy to exhaust; the failure was swallowed silently. When the API refuses, the update check now reads the public `releases.atom` feed instead (not rate limited). The feed has no pre-release flag, so there a tag with a pre-release suffix counts as a pre-release (a stable install is not offered a beta), and the installer and checksum URLs follow the fixed names `release.yml` uses; the SHA-256 check is unchanged.

## [0.4.0-beta.6] - 2026-10-20

Test release. Server image fixes found while running beta.5 on a real GPU server, and a new image with speaker separation. The desktop app is unchanged apart from the version, which makes this the first real test of the in-app update.

### Added
- **`-cuda-diarize` server image** (NVIDIA GPU + speaker separation with pyannote). Torch comes from the CUDA 12.6 index (`torch`/`torchaudio` 2.11.0): PyPI's Linux torch is now a CUDA 13 build, and two cuDNN builds next to Whisper's CUDA 12 libraries in one process would clash. CI builds it and checks that `torch`, `torchaudio` and `pyannote.audio` import and that torch reports CUDA 12. It has not run on a GPU yet. Use it with `REKAMIND_DIARIZER=pyannote` and `REKAMIND_HF_TOKEN`.
- Compose files pass through more settings: `REKAMIND_DIARIZER`, `REKAMIND_HF_TOKEN`, `REKAMIND_WHISPER_COMPUTE_TYPE`, `REKAMIND_GLOSSARY`, `REKAMIND_MAX_UPLOAD_MB`, `REKAMIND_LLM_CHUNK_CHARS`, and `REKAMIND_BIND` for the published address (`REKAMIND_PORT` was already there).

### Changed
- **The compose files publish the port on all interfaces (`0.0.0.0`) by default** (it was `127.0.0.1`), so a reverse proxy on another host can reach it. Allow it only from that proxy in the firewall, or set `REKAMIND_BIND=127.0.0.1` when the proxy runs on the same host.

### Fixed
- **The first transcription on a fresh server stalled while downloading the Whisper model.** On a real server the `large-v3` download stopped after about 130 MB (Hugging Face's Xet downloader; the network itself ran at about 110 MB/s). `HF_HUB_DISABLE_XET=1` is now set in the image and in the compose files; with it the 3 GB download finished in under two minutes.

### Measured
- On an RTX 4060 Ti (16 GB), one short recording: Whisper `large-v3` raised VRAM use by about 4.1 GB at its peak, and VRAM returned to within about 130 MB of the idle value as soon as the queue emptied. One short recording only.

## [0.4.0-beta.5] - 2026-10-20

Test release. Fixes desktop sign-in against a server behind Google's certificates, removes the dead-end error screen, and adds an in-app update notice.

### Added
- **Update notice in the desktop app.** The app checks GitHub Releases shortly after start and every 6 hours; when a newer release exists, a banner on the meetings page offers "Perbarui sekarang". One click downloads the Windows installer, verifies its SHA-256 against the release's `SHA256SUMS.txt` (a mismatch aborts and installs nothing), runs it and restarts the app. Refused while a recording, upload or engine install is running. A prerelease is only offered to someone already on a prerelease. On Linux the button opens the release page. The installer is not signed, so trust rests on GitHub's TLS and the repository's release permissions.

### Changed
- The three compose files now pass `REKAMIND_CORS_ORIGINS` with the desktop app's origins (`http://tauri.localhost`, `https://tauri.localhost`, `tauri://localhost`) as the default. Without it a desktop app in server mode reported "cannot reach the server" although the server was up. Documented in `docs/INSTALL.md`.

### Fixed
- **Desktop app stuck on the "cannot reach the server" screen.** The message said to check the server address in Settings, but Settings lives behind the sign-in, so there was no way out. That screen now has "Pakai mode lokal" (one click back to local mode, other settings kept) and "Ubah pengaturan server" (the desktop settings, openable without signing in).
- **Desktop sign-in ended with "native-tls: unable to find any user-specified roots in the final cert chain"** on servers whose certificate chains to a root Mozilla's bundle lacks (e.g. Google Trust Services via GlobalSign). The browser step succeeded, then the app's own call to the server failed. The Windows build now trusts the Windows certificate store, like the browser does (`recorder/src/api.rs`).

## [0.4.0-beta.4] - 2026-10-15

Test release. **The whole repository is now licensed under AGPL-3.0-or-later** (releases up to v0.4.0-beta.3 were MIT and stay MIT). Carries everything from beta.3.

### Changed
- Licence: MIT -> AGPL-3.0-or-later (`LICENSE`, `Cargo.toml`, `pyproject.toml`, image label, READMEs, docs). Added `THIRD_PARTY_NOTICES.md` (CC-BY-4.0 attribution for two pyannote models and a list of third-party licences, with what is verified and what is not) and a contributor licence statement in `CONTRIBUTING`.

## [0.4.0-beta.3] - 2026-10-15

Test release. First AMD GPU (Vulkan) release that has been run on real hardware (Ryzen AI 7 350, Radeon 860M), plus a fix for the engine test button on AMD.

### Fixed
- **"Uji mesin" said "No Vulkan device; using the CPU" on AMD even though transcription used the GPU** (`enginepack.py`): the probe ran `whisper-cli` with `-np`, which silences all of whisper.cpp's logging including the `ggml_vulkan: 0 = ...` line the app reads the device from. The probe now uses `-nt`. The fake `whisper-cli` in the tests mimics `-np` so this stays covered.

### Changed
- README (EN/ID): the AMD (Vulkan) engine is documented as tested on one Ryzen AI 7 350 (Radeon 860M). Stated plainly: speaker separation (pyannote) still runs on the CPU on AMD; accuracy against the CPU engine and 30+ minute meetings have not been measured; the progress bar moves per stage, not within a stage.

## [0.4.0-beta.2] - 2026-10-15

Test release. Fixes the recorder bug that produced choppy audio and empty transcripts on Windows, and adds experimental Intel (OpenVINO) and AMD (Vulkan) engines.

### Fixed
- **Recordings were choppy and transcripts came out empty on Windows** (`wasapi_backend.rs`): the `wasapi` crate reads a single ~10 ms packet per call, but the recorder called it once per 100 ms poll, so only ~10% of the audio was kept and the pacer padded the rest with silence; the VAD then removed all of it. It now drains every ready packet per poll (`drain_packets`, bounded).
- Installing speaker separation could stall at ~0.01 MB/s: `--extra-index-url` PyTorch made pip prefer `pypi.nvidia.com` for every `nvidia-*` wheel. `torch`/`torchaudio` now come from the PyTorch wheel pages (`--find-links`) and the `nvidia-*` packages from PyPI.
- A meeting with no tasks stayed in *Perlu ditinjau* forever (the only way out was deciding a task). It now finishes as *Selesai*; a failed summary still stays in review with its retry button.
- An all-empty JSON answer from the summary service was saved as a blank summary and shown as done. It is now retried and, if still empty, reported as an error with *Buat ulang ringkasan*.
- Three people were heard as two (and "UNKNOWN" counted as a speaker): the speaker count can be given as a hint, segments in a gap between turns take the nearest speaker, and speakers with nothing said are dropped when a meeting is reprocessed.
- The language switcher's popup was unreadable on hover (white text on white); it is now two buttons, and `<option>` colours are explicit everywhere.
- The audio player never played in the desktop app: an `<audio src>` cannot send the bearer token, so the server answered 401. Audio is now fetched with the token and played from a blob.

### Added
- **Number of speakers** hint per meeting (*Jumlah pembicara* / *Pisahkan ulang*), stored on the meeting (migration 0004) and passed to pyannote.
- A sentence spoken by two people is cut where the voice changes (word timestamps; a turn needs at least 3 words and 1 second).
- **Dengarkan rekaman** card on every meeting: play the computer audio or the microphone, even with an empty transcript.
- While recording with the local engine, one focused screen replaces the meeting list, tasks and settings (they cannot work then).
- Speaker separation is ticked by default when installing the engine; installing is blocked until a Hugging Face token is saved (it can be pasted in the notice), and a successful install with it turns the setting on.
- Engine install shows a download progress bar with speed and a stall warning; the raw log is hidden behind *Tampilkan log*.
- `docs/API_KEYS.md` / `docs/API_KEYS.id.md`: step-by-step guide for a Hugging Face token and for a Groq key or any OpenAI-compatible summary service.


### Fixed
- Intel GPU (OpenVINO) engine install failed with `ResolutionImpossible`: `optimum-intel[openvino]` needs `nncf`, which caps numpy below 2.5, while the frozen backend shipped numpy 2.5.4 and the install pinned to it, so pip fell back to ancient releases needing an unpublished OpenVINO build. The backend now requires `numpy<2.5`, the install retries once without the numpy/av pins on `ResolutionImpossible`, and CI resolves every engine kind with the real pip (`scripts/check_engine_pack_resolves.py`). Only affects the unreleased Intel/AMD branches.
- Engine install could die with `OSError: [Errno 22] Invalid argument` (exit code 120) when pip printed its first download progress line: the desktop app's output reader stopped at the first non-UTF-8 line (the progress line's ellipsis in a cp1252 console) and closed the pipe. The reader now never stops early (invalid bytes are replaced), the backend CLI writes UTF-8, install output is ASCII, and a closed pipe can no longer abort pip or turn a success into exit code 120. Regression introduced after beta.1 on the feature branches; beta.1 is not affected.

### Changed
- Engine install is observable and more robust: a diagnostics block (pip version, package sources/proxies with credentials masked, host reachability), a progress line every few seconds with speed, a warning when a download stalls, longer timeouts/retries, and resumable downloads on pip >= 25.1. Arguments for CPU/NVIDIA installs are otherwise unchanged.

### Added
- AMD GPU (integrated Radeon 680M/780M/860M and other Vulkan GPUs) transcription through whisper.cpp built with Vulkan: engine kind `vulkan` (*Pasang untuk GPU AMD (Vulkan)*), `whisper_device=vulkan`, program built by CI (`engine-assets` workflow) and downloaded with SHA-256 verification, ggml models from Hugging Face. **Experimental: tested with a fake program only, not verified on real hardware.**
- Intel GPU (integrated Arc/Iris Xe, e.g. Core Ultra 7 155H) transcription through OpenVINO: new engine kind `openvino` in the engine pack (*Pasang untuk Intel GPU*), `whisper_device=intel`, GPU detection to recommend it, falls back to the CPU when the GPU cannot load the model. **Experimental: unit-tested with fakes, and reported working by hand on a Core Ultra 7 155H; no speed/accuracy measurements recorded.**

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
