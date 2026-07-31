# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Always respond to the user in Bahasa Indonesia in this repository, regardless of the language of their message.

## What this is

A Windows-only desktop app (Tkinter UI) that records mic + system-audio (WASAPI loopback) during a meeting, transcribes it (faster-whisper), diarizes speakers (pyannote), and generates a Bahasa Indonesia Minutes-of-Meeting docx via a Groq-hosted LLM. Recording and processing are deliberately decoupled: "Mulai Rekam"/"Stop Rekam" only captures audio; transcription and summarization are separate, manually-triggered, per-meeting actions from the Riwayat (history) tab.

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

Config comes from `.env` (see `.env.example`): Postgres connection vars are required; `GROQ_API_KEY` and `HF_TOKEN` (HuggingFace, for pyannote model weights) are optional but needed for summarization/diarization to work. `ASR_BACKEND_OVERRIDE` forces `cuda`/`openvino`/`cpu` instead of auto-detecting.

## Architecture

### Two independent audio→text pipelines

- **Live pipeline** (`app/live/`): runs while recording, gives a near-real-time preview. Each of mic/speaker gets its own `SpeechSegmenter` (silero-vad) feeding a small ASR model (`build_live_transcriber`, e.g. faster-whisper `small`) and a **process-isolated** diarizer (`ProcessIsolatedDiarizer`, `pyannote/speaker-diarization-3.1` in a separate OS process — pyannote/CUDA has been observed to crash the whole process natively on bad input, so isolating it means only that disposable worker dies). The live diarize loop (`LiveDiarizeLoop`) re-diarizes only the **last ~5 minutes** of `speaker.wav` per tick (not the whole growing file — that used to make tick time grow unboundedly with meeting length and eventually blow past the worker timeout, leaking orphaned worker processes each holding a full model copy). Live text/relabel events flow to the UI through `LiveSession.on_update` → `MainWindow.push_live_event` (a thread-safe queue drained on the Tk main loop).
- **Batch pipeline** (`app/pipeline/transcribe.py`, `summarize.py`): triggered manually per meeting from Riwayat ("Transkrip"/"Ringkasan"). Re-transcribes the full WAVs with a larger model (`large-v3`, `int8` on CUDA) and re-diarizes the *entire* recording (no time cap) — this is the authoritative, saved transcript; the live preview above is provisional and gets fully replaced.

Both call into the same `app/pipeline/merge.py::merge_segments`, which assigns each ASR segment a speaker label by finding the diarization turn with the most time overlap.

### ASR/diarization backend selection

`app/asr/detect.py` auto-picks `cuda` (via `ctranslate2.get_cuda_device_count()`, not `torch.cuda` — torch is only a transitive dep here) → `openvino` (GPU/NPU) → `cpu`, overridable via `asr_backend_override`. `app/main.py::build_models`/`build_transcriber` wire the chosen backend to concrete `TranscriberBackend` implementations in `app/asr/`. Heavy batch models (`_models` global in `main.py`) and the live model/diarizer (`live_transcriber`/`live_diarizer` closures) are lazy singletons — built on first use, then reused for the rest of the app run, never unloaded.

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
