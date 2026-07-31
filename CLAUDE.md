# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Rekamind** — a Windows-only desktop app (Tkinter UI) that records mic + system-audio (WASAPI loopback) during a meeting, transcribes it (faster-whisper), diarizes speakers (pyannote), and generates a Bahasa Indonesia Minutes-of-Meeting docx via a Groq-hosted LLM. Recording and processing are deliberately decoupled: "Mulai Rekam"/"Stop Rekam" only captures audio; transcription and summarization are separate, manually-triggered, per-meeting actions from the Riwayat (history) tab. Local-first by default (SQLite, on-device ASR/diarization); Postgres and MinIO-based multi-device sync are opt-in for office/team deployments.

## Commands

```bash
# Install (editable install from pyproject.toml, no lock file)
pip install -e .

# Run the app (Windows only — needs pyaudiowpatch/WASAPI)
python -m app.main

# Run the full test suite (hardware- and postgres-marked tests are excluded by default, see pytest.ini)
pytest

# Run a single test
pytest tests/live/test_session.py::test_start_feeds_queued_chunks_through_pipeline_and_reports_text_events

# Run tests that need a real audio device or a real Postgres server (normally skipped)
pytest -m hardware
pytest -m postgres
```

Two ways config gets loaded, picked by `app/settings_store.py::is_dev_mode()` (true iff a `.env` file exists in the repo root):

- **Dev mode** (this repo checkout): config comes from `.env` (see `.env.example`) via `pydantic-settings`. `STORAGE_BACKEND` defaults to `sqlite` — Postgres vars (`POSTGRES_HOST`/`PORT`/`USER`/`PASSWORD`/`DB`) are only read when `STORAGE_BACKEND=postgres`. `GROQ_API_KEY` and `HF_TOKEN` (HuggingFace, for pyannote model weights) are optional but needed for summarization/diarization to work. `ASR_BACKEND_OVERRIDE` forces `cuda`/`openvino`/`cpu` instead of auto-detecting.
- **Packaged mode** (no `.env`, e.g. an installed `.exe` on a colleague's machine): `app/ui/setup_wizard.py::SetupWizard` runs on first launch and writes the same fields to `%LOCALAPPDATA%\MeetingRecorder\config.json` (`app/settings_store.py::save_packaged_config`). A `device_id` (`uuid.uuid4().hex`) is generated once here and preserved across resaves — it's what tags every meeting this install creates and what namespaces its objects in MinIO.

`app/config.py::get_settings()` (an `lru_cache`d singleton, cleared explicitly after the wizard writes new config) branches on `is_dev_mode()` and returns a `Settings` instance either way — the rest of the app never checks dev-vs-packaged directly.

## Architecture

### Two independent audio→text pipelines

- **Live pipeline** (`app/live/`): runs while recording, gives a near-real-time preview. Each of mic/speaker gets its own `SpeechSegmenter` (silero-vad) feeding a small ASR model (`build_live_transcriber`, e.g. faster-whisper `small`) and a **process-isolated** diarizer (`ProcessIsolatedDiarizer`, `pyannote/speaker-diarization-3.1` in a separate OS process — pyannote/CUDA has been observed to crash the whole process natively on bad input, so isolating it means only that disposable worker dies). The live diarize loop (`LiveDiarizeLoop`) re-diarizes only the **last ~5 minutes** of `speaker.wav` per tick (not the whole growing file — that used to make tick time grow unboundedly with meeting length and eventually blow past the worker timeout, leaking orphaned worker processes each holding a full model copy). Live text/relabel events flow to the UI through `LiveSession.on_update` → `MainWindow.push_live_event` (a thread-safe queue drained on the Tk main loop).
- **Batch pipeline** (`app/pipeline/transcribe.py`, `summarize.py`): triggered manually per meeting from Riwayat ("Transkrip"/"Ringkasan"). Re-transcribes the full WAVs with a larger model (`large-v3`, `int8` on CUDA) and re-diarizes the *entire* recording (no time cap) — this is the authoritative, saved transcript; the live preview above is provisional and gets fully replaced.

Both call into the same `app/pipeline/merge.py::merge_segments`, which assigns each ASR segment a speaker label by finding the diarization turn with the most time overlap.

### ASR/diarization backend selection

`app/asr/detect.py::detect_backend()` auto-picks `cuda` (via `ctranslate2.get_cuda_device_count()`, not `torch.cuda` — torch is only a transitive dep here) → `openvino` (GPU/NPU) → `cpu` (any machine with `ctranslate2` importable), overridable via `asr_backend_override`. If none of the three work it raises `UnsupportedHardwareError` instead of silently returning `"cpu"` — `main()` catches this immediately after `get_settings()` (before any DB/window setup — this ordering matters, see git history) and shows a `messagebox.showerror` + `sys.exit(1)` rather than letting the app limp into a crash later. `app/main.py::build_models`/`build_transcriber` wire the chosen backend to concrete `TranscriberBackend` implementations in `app/asr/`. Heavy batch models (`_models` global in `main.py`) and the live model/diarizer (`live_transcriber`/`live_diarizer` closures) are lazy singletons — built on first use, then reused for the rest of the app run, never unloaded.

### Storage backend: SQLite vs Postgres

`Settings.storage_backend` (`"sqlite"` default, or `"postgres"`) picks the `database_url` a session factory connects to (`app/config.py::Settings.database_url`, a computed property — never stored). SQLite needs zero configuration: its path is always `%LOCALAPPDATA%\MeetingRecorder\meeting.db` (`app/settings_store.py::sqlite_db_path`), same in dev and packaged mode. Postgres requires the five `postgres_*` fields and is meant for a user who already runs a shared Postgres server. Both go through the same `app/storage/db.py::make_engine`/`init_db`/`make_session_factory` and the same SQLAlchemy models — nothing in `app/storage/` branches on which backend is active.

### Device identity and multi-device sync

Every install has a `device_id` (+ human-readable `device_label`, default `socket.gethostname()`) set once by the setup wizard and stored in `Settings`. Every `Meeting` row carries the `device_id`/`device_label` of the machine that recorded it (`app/storage/models.py`), so a synced history view can tell "your meetings" from "a colleague's meetings" (`RecorderController.local_device_id`, checked in `app/ui/history_view.py::_update_action_panel` to hide Transkrip/Ringkasan/Coba Lagi for meetings you don't own — Hapus/Lihat Transkrip/Unduh Docx stay available regardless).

Sync itself (`app/sync/minio_client.py`, only active when `Settings.minio_is_configured` — all four `minio_*` fields non-empty, otherwise zero network calls) is manifest-based, not a shared database:

- **`push()`** uploads a `manifest.json` (title, timestamps, status, final transcript segments, summary) for every meeting this device owns to `<device_id>/<meeting_dir_uuid>/manifest.json` in the configured bucket, every sync. The WAVs and `mom.docx` are uploaded once each, gated by `Meeting.synced_at`.
- **`pull()`** lists every `manifest.json` NOT under this device's own prefix and materializes each as a local `Meeting` + `TranscriptSegment` + `Summary` row, skipping ones already pulled (matched by `recording_dir`).
- **`download_file()`** / `RecorderController.ensure_docx_available()` fetch the actual `mom.docx` for a pulled meeting on demand (click "Unduh Docx"), not eagerly — most pulled meetings are just browsed, never opened.

Both `pull()` and `download_file()` treat the `device_id`/`meeting_dir` segments of an object name as **untrusted input**: they come from whatever another device (potentially compromised, sharing the same bucket) wrote. Both validate against `_SAFE_PATH_COMPONENT` (the exact charset `uuid4().hex` ever produces) before building a local path, and `pull()` additionally resolves the path and checks `is_relative_to(recordings_root)` — this exists because building filesystem paths directly from unvalidated remote object names is a path-traversal vulnerability, found and fixed during Plan #4's implementation.

### Meeting lifecycle / status state machine

`Meeting.status` in `app/storage/models.py` moves: `scheduled → recording → recorded → transcribing → transcribed → summarizing → completed`, or `failed` (with `failed_stage` + `error_message` for a retry-in-place UI action). `app/pipeline/recovery.py::recover_abandoned_meetings` runs at startup and resets any meeting stuck in an in-progress status (`recording`/`transcribing`/`summarizing`) — the only way that happens is the app dying mid-action.

### Async DB access pattern

`app/storage/db.py::make_engine` uses `NullPool` for Postgres (not sqlite): the app calls `asyncio.run()` repeatedly from sync Tk callbacks rather than running one long-lived event loop, and a pooled asyncpg connection is bound to the loop that created it — reusing one across `asyncio.run()` calls would hand back a dead connection. Every DB-touching method in `app/ui/controller.py` follows the same shape: build a coroutine, `asyncio.run()` it, called from a background thread spawned by the Tk layer (never the UI thread).

### UI structure

`app/ui/window.py::MainWindow` has two tkraise()-stacked frames (Meeting Baru / Riwayat), driven by `app/ui/controller.py::RecorderController` (business logic, no Tk imports) and `app/ui/history_view.py::HistoryView` (per-meeting action buttons whose visibility depends on `Meeting.status`). Background thread results are handed back to the UI thread via `root.after(0, ...)`, never touched directly from a worker thread.

## Testing conventions

- DB-dependent tests use `sqlite+aiosqlite:///:memory:` via `make_engine`/`init_db`/`make_session_factory`, not a real Postgres (those are `@pytest.mark.postgres`, run separately).
- Tkinter tests guard with a `_tk_available()`/`@pytest.mark.skipif` check (no display in some CI/dev environments), and use a `_pump_until(root, predicate)` helper — `root.after(...)` callbacks from background threads are only honored while the main thread is inside `mainloop()`, so plain `root.update()` polling doesn't work.
- Timing-sensitive live-pipeline tests (`tests/live/`) use real `threading`/`queue` objects with short polling loops against a deadline rather than mocking the concurrency away.
