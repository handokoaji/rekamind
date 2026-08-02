# Rekamind

**Record it. Remember it. Keep it yours.**

Rekamind is a local-first AI meeting assistant for Windows. It records your
mic and system audio during a meeting, transcribes it, tells speakers apart,
and generates a Bahasa Indonesia Minutes-of-Meeting document — all on your
own machine, with an optional sync layer so an entire office can see each
other's meetings without a shared cloud subscription.

![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Status](https://img.shields.io/badge/status-active%20development-yellow)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Why Rekamind

Most AI meeting notetakers (Otter, Notta, Fireflies, Rekap.AI) require
uploading your raw audio to their servers. Most local-first alternatives
(Meetily, ownscribe, Recap) stop at a single laptop with no way to share
results with a team. Rekamind sits between the two:

- **Nothing leaves your machine by default.** Transcription (faster-whisper)
  and speaker diarization (pyannote) both run locally. The only optional
  network calls are to Groq (for the summary LLM) and, if you turn it on,
  your own MinIO bucket.
- **Built for an office, not just one person.** Every install gets a
  `device_id`. Turn on MinIO sync and colleagues' meetings show up in your
  history view — nobody needs a shared database server.
- **Bahasa Indonesia is the default output**, not a translation bolted onto
  an English-first product.
- **Two transcription passes, on purpose.** A fast local model gives you a
  live preview while recording so you know it's actually working; a larger
  model re-transcribes the full recording afterward as the authoritative
  version.
- **Deploy how you want.** SQLite + local files needs zero setup. Postgres +
  MinIO is there when an office wants shared visibility.

## Features

- Simultaneous mic + system-audio (WASAPI loopback) capture
- Near-real-time live transcription and speaker preview while recording
- Full-recording re-transcription and re-diarization after the meeting
  (faster-whisper `large-v3`, pyannote speaker-diarization-3.1)
- Bahasa Indonesia Minutes-of-Meeting generation via Groq, exported to `.docx`
- SQLite (zero-config) or Postgres (multi-seat) storage backend
- Optional MinIO-based sync so meetings recorded on one device are visible
  and downloadable from another
- Automatic CUDA / CPU backend detection with a clear error instead of a
  silent slow fallback (an OpenVINO backend exists for Intel GPU/NPU but is
  not yet auto-selected — see `ASR_BACKEND_OVERRIDE` below)
- Meeting lifecycle recovery — an app crash mid-transcription doesn't leave
  a meeting stuck; it's reset and retryable on next launch

## Quickstart

Windows only — recording depends on WASAPI loopback via `pyaudiowpatch`.

`pip install -e .` alone pulls PyPI's default `torch` wheel, which has **no
CUDA support compiled in** (`pyproject.toml` can't pin a per-package index
URL). Install the right `torch` build for your hardware *first*, so
`pip install -e .` sees the requirement already satisfied and leaves it in
place:

```bash
# NVIDIA GPU (e.g. GTX 1080 Ti and other CUDA-capable cards)
pip install torch==2.13.0+cu126 --index-url https://download.pytorch.org/whl/cu126
pip install -e .

# No NVIDIA GPU (Intel, AMD, or CPU-only — e.g. Core Ultra 7 155H)
pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

Then:

```bash
cp .env.example .env   # fill in your storage backend + API keys
python -m app.main
```

`GROQ_API_KEY` (summarization) and `HF_TOKEN` (pyannote model weights, for
diarization) are optional — the app runs without them, just without
summaries or speaker labels. See `.env.example` for the full list of
settings, including `STORAGE_BACKEND` (`sqlite` or `postgres`) and the
`ASR_BACKEND_OVERRIDE` escape hatch if auto-detection picks the wrong
hardware backend. On multi-device setups, `device_id`/`device_label` default
to the machine's hostname in dev mode, so each machine gets a distinct
identity with no manual configuration.

A packaged `.exe` installer (no Python required) is in progress — see
Roadmap below.

## Architecture

Recording and processing are deliberately decoupled: "Mulai Rekam" / "Stop
Rekam" only captures audio. Transcription and summarization are separate,
manually-triggered actions per meeting from the history tab. Full
architectural notes — the live vs. batch pipeline split, backend detection,
the async DB access pattern, and UI structure — live in `CLAUDE.md` at the
repo root.

## Testing

```bash
pytest                 # full suite; hardware- and postgres-marked tests excluded by default
pytest -m hardware      # needs a real audio device
pytest -m postgres      # needs a real Postgres server
```

## Roadmap

- [x] SQLite storage backend as a zero-config alternative to Postgres
- [x] First-run setup wizard
- [x] Device identity (`device_id`) for multi-device history
- [x] MinIO-based file/metadata sync across devices
- [x] Hardware capability detection hardening (CUDA / OpenVINO / CPU)
- [ ] Packaged Windows `.exe` installer (PyInstaller + Inno Setup)

## License

[MIT](LICENSE)
