# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Always respond to the user in Bahasa Indonesia in this repository, regardless of the language of their message.

## What this is

**Rekamind** records a meeting (microphone + system audio as two tracks), then transcribes it, separates speakers and produces a summary, decisions and a task list. Recording and processing are deliberately decoupled: nothing heavy runs during a meeting, and processing happens afterwards on a local or remote backend. Local-first; a shared team server (Docker, Google sign-in) is optional. Licensed AGPL-3.0-or-later. Beta (0.x).

The old v1 Tkinter app was removed from the tree; it lives in git history and tags `v0.1.0` to `v0.3.0` (`docs/archive-v1/` keeps its notes). v2 is not compatible with it.

## Layout

| Path | What |
|---|---|
| `recorder/` | Rust recorder: WASAPI (Windows) / `parec` (Linux) to two 16 kHz mono WAVs. No ASR, VAD or network while recording. Crash-tolerant WAVs, `record` / `upload` / `recover` CLI. |
| `desktop/` | Tauri 2 shell (tray, global hotkey `Ctrl+Alt+R`). Thin: logic lives in `recorder/`. Rust to UI contract: `desktop/contract/ui-state.json` (golden file written by Rust tests, read by web tests). |
| `web/` | React + Vite + TS + Tailwind SPA, used both inside Tauri and served by the backend. Playwright e2e in `web/e2e*`. |
| `server/rekamind_server/` | FastAPI backend: `api.py`, DB-backed job queue (`jobs.py`, `worker.py`), `pipeline.py`, `engines/` (CUDA/faster-whisper, Vulkan/whisper.cpp, OpenVINO, fake), `enginepack.py` (on-demand engine install), `auth/` (Google OIDC + PKCE), `deadlines.py`, `export.py` (docx/md/json), `integrations.py` (GitHub, GitLab, HMAC webhook), `vault.py` (encrypts integration secrets), Alembic `migrations/`. |
| `docs/` | `INSTALL`, `AUTH`, `API_KEYS`, `INTEGRATIONS`, `RELEASING` (each also `.id.md`), `v2/ARCHITECTURE.md` (Indonesian, the design record). |

## Commands

```bash
# backend (SQLite, fake engines) on :8787
pip install -e "server[dev]" && REKAMIND_ENGINES=fake python -m rekamind_server
pytest server -q

# UI
cd web && npm ci && npm run dev          # proxies /api to the backend above
cd web && npx vitest run                 # unit tests
cd web && npx playwright test            # e2e: real backend + production build

# recorder
cd recorder && cargo test

# local installer (Windows: nsis, Linux: deb)
python scripts/build_desktop.py
```

`server/tests/test_enginepack.py::test_selftest_runs_the_distlib_launcher_lookup_that_failed_in_the_frozen_windows_build` fails in some sandboxes (no pip launcher); it passes in CI.

## Invariants worth knowing

- **Nothing heavy during a meeting.** The desktop controller refuses to start the local backend while recording, whatever the UI asks; the backend is started on demand after Stop and stopped after 10 idle minutes.
- **No live transcript.** The recorder shows levels and duration only.
- **Diarization is for the speaker track only**; the mic track is always the local user.
- **Tasks are human-confirmed**: `suggested -> confirmed | rejected`; only confirmed tasks are exported or pushed. Deadlines are computed deterministically (`deadlines.py`), not by the LLM; vague phrases are flagged `approximate`.
- **Secrets**: integration tokens are encrypted by `vault.py` (HKDF key from `REKAMIND_SECRET_KEY`, or a generated `secret.key` in single-user modes). Tokens sealed with the older plain-SHA-256 key stay readable. Never log pip/proxy variable values (`enginepack.describe_environment` logs names only).
- **Untrusted URLs**: integration destinations go through `check_destination` (no private networks on a shared server).
- **Engine contract**: engines implement `Transcriber / Diarizer / Extractor` from `server/rekamind_server/engines/base.py`; the pipeline never depends on a concrete engine.
- Only the transcript text is sent to the summary provider (default Groq, any OpenAI-compatible API works); audio never leaves the machine.

## Testing conventions

- Backend tests use SQLite and the fake engines (`REKAMIND_ENGINES=fake`); Postgres and S3 paths use moto/optional extras.
- A change on either side of the Rust/UI contract fails a test, not the app: regenerate `desktop/contract/ui-state.json` through the Rust test, never by hand.
- CI is `.github/workflows/v2-ci.yml` (server, web, recorder, desktop, image builds, engine-resolve). Workflows should declare least-privilege `permissions:`.
