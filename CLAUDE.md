# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Always respond to the user in Bahasa Indonesia in this repository, regardless of the language of their message.

## What this is

**Rekamind** — a Windows-only desktop app (Tkinter UI) that records mic + system-audio (WASAPI loopback) during a meeting, transcribes it (faster-whisper), diarizes speakers (pyannote), and generates a Bahasa Indonesia Minutes-of-Meeting docx via a Groq-hosted LLM. Recording and processing are deliberately decoupled: "Mulai Rekam"/"Stop Rekam" only captures audio; transcription and summarization are separate, manually-triggered, per-meeting actions from the Riwayat (history) tab. Local-first by default (SQLite, on-device ASR/diarization); Postgres and MinIO-based multi-device sync are opt-in for office/team deployments.

## Commands

```bash
# Install torch for your hardware FIRST -- pyproject.toml can't pin a
# per-package index URL, so a bare `pip install -e .` silently pulls PyPI's
# CPU-only torch wheel even on a CUDA machine. See README.md's Quickstart for
# the exact per-machine commands (cu126 vs cpu wheel).
pip install torch==2.13.0+cu126 --index-url https://download.pytorch.org/whl/cu126  # or the cpu wheel

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

- **Live pipeline** (`app/live/`): runs while recording, gives a near-real-time preview. Each of mic/speaker gets its own `SpeechSegmenter` (silero-vad, force-closing any segment past `MAX_SEGMENT_SECONDS=20` so a single live ASR call is always well under any 30s chunk boundary) feeding a small ASR model (`build_live_transcriber`, e.g. faster-whisper `small`, `int8` — same reasoning as the batch model below) and a **process-isolated** diarizer (`ProcessIsolatedDiarizer`, `pyannote/speaker-diarization-3.1` in a separate OS process — pyannote/CUDA has been observed to crash the whole process natively on bad input, so isolating it means only that disposable worker dies). The live diarize loop (`LiveDiarizeLoop`) re-diarizes only the **last ~5 minutes** of `speaker.wav` per tick (not the whole growing file — that used to make tick time grow unboundedly with meeting length and eventually blow past the worker timeout, leaking orphaned worker processes each holding a full model copy). `LiveDiarizeLoop.stop()` also tears down the worker process itself (duck-typed `getattr(diarizer, "shutdown", None)`) on every real "Stop Rekam" — the `ProcessIsolatedDiarizer` object stays cached in `main.py`'s closure, so the next meeting's first tick just respawns a fresh worker lazily, same as the existing crash/timeout recovery. Live text/relabel events flow to the UI through `LiveSession.on_update` → `MainWindow.push_live_event` (a thread-safe queue drained on the Tk main loop). The live pipeline's backend can be picked independently of the batch pipeline's via `Settings.live_asr_backend_override` (empty by default, meaning "same backend as batch") — `main()` computes `live_backend_name = settings.live_asr_backend_override or backend_name` once and threads it through `build_live_transcriber`/`diarizer_device` inside `live_session_factory`, leaving every batch call site (`load_models`, `transcribe_fn`, `summarize_fn`) on the plain `backend_name`, untouched.
- **Batch pipeline** (`app/pipeline/transcribe.py`, `summarize.py`): triggered manually per meeting from Riwayat ("Transkrip"/"Ringkasan"). Re-transcribes the full WAVs with a larger model (`large-v3`, `int8` on CUDA) and re-diarizes the *entire* recording (no time cap) — this is the authoritative, saved transcript; the live preview above is provisional and gets fully replaced.

Both call into the same `app/pipeline/merge.py::merge_segments`, which assigns each ASR segment a speaker label by finding the diarization turn with the most time overlap.

### ASR/diarization backend selection

`app/asr/detect.py::detect_backend()` auto-picks `cuda` (via `ctranslate2.get_cuda_device_count()`, not `torch.cuda` — torch is only a transitive dep here) → `cpu` (any machine with `ctranslate2` importable), overridable via `asr_backend_override`. `openvino` (`app/asr/openvino_backend.py`, Intel iGPU via `optimum-intel`) exists but is **deliberately not auto-selected**: it's only been validated on the one Intel machine this project has tested against (an Intel Core Ultra 7 155H — CPU and GPU/iGPU paths both confirmed working there, including `OpenVinoWhisperBackend.transcribe` chunking audio into `MAX_TRANSCRIBE_SECONDS` (30s) windows so a real, full-length meeting recording transcribes correctly instead of hard-failing past the first window), not "any Intel GPU" in general — it's only reachable via `ASR_BACKEND_OVERRIDE=openvino`. An NPU backend (`openvino-genai`'s `WhisperPipeline`, targeting the same machine's NPU) was built and evaluated, then removed: the NPU compiler only supports greedy decoding (beam search fails outright with a static-shape tensor error), which on real Indonesian speech reliably degenerated into repeated phrases or drifted into English even with `repetition_penalty`/`min_new_tokens` tuning — confirmed via side-by-side transcription of the same real recording on iGPU (correct, stable Indonesian) vs NPU (garbled English). Not worth resurrecting without an upstream NPU decoding fix. If neither cuda nor cpu work, `detect_backend()` raises `UnsupportedHardwareError` instead of silently returning `"cpu"` — `main()` catches this immediately after `get_settings()` (before any DB/window setup — this ordering matters, see git history) and shows a `messagebox.showerror` + `sys.exit(1)` rather than letting the app limp into a crash later. `app/main.py::build_models`/`build_transcriber` wire the chosen backend to concrete `TranscriberBackend` implementations in `app/asr/` — `FasterWhisperBackend`, `OpenVinoWhisperBackend`, `Diarizer`, and `ProcessIsolatedDiarizer` are all imported *inside* the functions that use them, not at module level: each transitively pulls in torch/pyannote/transformers/openvino (measured: ~800MB+ RSS), so `import app.main` alone must not pay that cost regardless of which backend a given machine ends up using. `SpeakerSegment` lives in the separate, lightweight `app/diarization/base.py` for the same reason — `app/diarization/diarizer.py` re-exports it for backward compatibility, but anything that only needs the dataclass (e.g. `app/pipeline/merge.py`) imports it from `base` directly to avoid dragging in the heavy module. Heavy batch models (`_models` global in `main.py`) and the live model/diarizer (`live_transcriber`/`live_diarizer` closures) are lazy singletons — built on first use, then reused across the app run; `_models` additionally self-unloads after 15 minutes of inactivity via a lazily-started daemon thread (`_idle_unload_loop`/`_unload_models_if_idle`), since it's the largest resident allocation (`large-v3` + pyannote) and a meeting sitting untouched in Riwayat shouldn't hold it forever.

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
