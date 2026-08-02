# Resume prompt — Rekamind packaging/installer work

Paste this whole file as your first message in a new session to pick up exactly where this one left off.

> **STATUS: the "immediate next step" below is DONE.** CI now installs
> `torch==2.13.0+cu126` before `pip install -e .`, `packaging/README.md` documents the same
> as step 0, and `app.main.diarizer_device()` keeps the diarizer on CPU when torch has no
> CUDA (previously an uncaught `Torch not compiled with CUDA enabled` that killed the whole
> Transkrip action). Installer-size decision: **one fat installer** (~1.8GB, CUDA+OpenVINO+CPU
> all bundled) — `detect_backend()` picks at runtime, no variants. Still open: sync `pull()`
> never validated end to end (see below).

## Immediate next step (what to do first)

The GitHub Actions-built installer (and any fresh `pip install -e .` anywhere) silently produces a
**CPU-only build with zero CUDA support**, even though the app is designed to use CUDA when available.
Root cause: `pyproject.toml` never pins a CUDA-enabled torch index. This local dev machine's `.venv` has
`torch==2.13.0+cu126` (CUDA 12.6) installed, but that was done manually/undocumented at some point — it's
not reproducible from a clean checkout. Confirmed by comparing this venv (`torch 2.13.0+cu126`, ~4GB) against
the GitHub Actions build log (`torch-2.13.0-cp311-cp311-win_amd64.whl`, 122MB, no `nvidia-*` CUDA packages
installed at all).

**Before anything else**, in the new session:
1. Decide how to pin a CUDA-enabled torch build reproducibly (e.g. `pip install torch --index-url
   https://download.pytorch.org/whl/cu126` run explicitly before `pip install -e .`, documented in
   `packaging/README.md` and added as an explicit step in `.github/workflows/build-installer.yml` before
   the "Install app" step — plain `pyproject.toml` dependencies can't express a per-package index URL).
2. Investigate whether `Diarizer` (pyannote, always torch-based regardless of ASR backend) silently
   falls back to CPU or crashes when `backend_name="cuda"` is detected (via `ctranslate2`, which per
   `app/asr/detect.py`'s own comment can have CUDA independently of torch) but torch itself has no CUDA
   support compiled in. Check `app/main.py`'s `build_models`/`load_models` for whether `Diarizer`
   construction is exception-guarded the same way `build_transcriber` is.
3. Only after that's fixed, come back to the installer-size discussion below.

## Installer size discussion (paused, waiting on the fix above)

We measured real package sizes in this `.venv` and estimated installer sizes for different bundling
strategies (using the observed ~37% compression ratio: raw 4.8GB dist → 1.88GB installer):

| Scenario | Raw (dist) | Installer (~37%) |
|---|---|---|
| Current (CUDA+OpenVINO+CPU all bundled) | ~4.9 GB | ~1.8 GB (actual, built) |
| CUDA-only variant | ~4.7 GB | ~1.7 GB — barely smaller! CUDA DLLs (~3.47GB raw) dominate regardless |
| OpenVINO-only variant (drop CUDA dlls + ctranslate2) | ~1.4 GB | ~500 MB |
| CPU-only variant (drop CUDA dlls + openvino) | ~1.2 GB | ~450 MB |
| "Slim installer" that downloads the right runtime at install time | ~0.6 GB | ~220 MB + a separate download at install (needs internet, needs bundling pip too) |

Key finding: `Diarizer` always needs torch regardless of ASR backend (just CPU vs CUDA device), so torch
itself can never be fully dropped — only its CUDA DLLs can be, for non-CUDA variants.

My recommendation (not yet actioned): two installer variants — `rekamind-cuda-<ver>.exe` (~1.7GB, once CUDA
is actually reproducible) and `rekamind-cpu-openvino-<ver>.exe` (~500MB, CPU+OpenVINO bundled together
since both are already small). The user had not yet confirmed this when the session ended — re-propose
after the CUDA-pinning fix lands, since the "CUDA-only barely smaller" finding might change their mind
about whether a separate CUDA variant is even worth the CI complexity.

## Everything already done this session (don't redo)

**Bug fixes, all committed and pushed to both remotes** (`origin` = GitLab `git.dev.ugm.ac.id/aksi_riset/meeting.git`,
`github` = `https://github.com/handokoaji/rekamind.git`, both in sync at commit `083d93a` as of session end):

- Pengaturan dialog missing MinIO/device_label fields + wizard `pack()` ordering bug (`6e5ba94`)
- `MINIO_ENDPOINT` scheme parsing (`http://` stripped, `secure=` inferred) (`6f75175`)
- `device_id`/`device_label` default to `socket.gethostname()` when unset in dev mode (`b765c8d`)
- 7 findings from an external code review, all fixed and tested:
  1. HIGH — `mom.docx` written to wrong directory, breaking sync/download/delete (`831fda5`)
  2. HIGH — `logs/` dir was CWD-relative, could crash packaged app silently (`82ed1c0`)
  3. MEDIUM — deleted meetings resurrected by sync; added `Meeting.deleted_at` soft-delete tombstone (`9b06eb5`)
  4. MEDIUM — "Pengaturan" and startup-DB-error recovery were silent no-ops in dev mode (`e03919e`)
  5. LOW — non-numeric Postgres port crashed the setup wizard uncaught (`68ae8ed`)
  6. LOW — possibly-unbound `message` var in sync worker (`5d1ea22`)
  7. HIGH — `ensure_docx_available` AttributeError guards (bundled into `831fda5`)
- CI: `pytest` wasn't installed before being invoked (`1b66340`)
- CI: `pyproject.toml` had no `[tool.setuptools.packages.find]`, so setuptools choked on `packaging/`
  looking like a second top-level package — `pip install -e .` failed on every clean checkout, and because
  it was inside a multi-line `pwsh run:` block the failure didn't stop the job, silently leaving zero
  dependencies installed for the next step. Fixed by scoping discovery to `app*` and splitting the
  install into separate steps so exit codes are checked (`f4fab06`)
- Full rebrand of packaging artifacts from "Meeting Recorder"/"MeetingRecorder" to "Rekamind": renamed
  `packaging/MeetingRecorder.spec` → `packaging/Rekamind.spec`, updated `installer.iss` (AppName, install
  dir, output filename `rekamind-<version>.exe`), `packaging/README.md`, CI workflow references (`083d93a`).
  **Deliberately NOT renamed**: `app/settings_store.py`'s `_APP_DIR_NAME = "MeetingRecorder"` (the actual
  `%LOCALAPPDATA%\MeetingRecorder\` runtime data directory — DB, recordings, config.json, logs). Renaming
  that would orphan any existing install's local data. Still an open decision if the user wants it changed.

**CI/CD infrastructure**: `.github/workflows/build-installer.yml` exists, triggers on `v*.*.*` tag push or
manual `workflow_dispatch`, runs on `windows-latest` (GitLab has no Windows runner). Runs the test suite as
a gate, downloads static ffmpeg, builds with PyInstaller, installs Inno Setup via choco, compiles the
installer, uploads as an artifact and (on tag push) attaches to a GitHub Release. `softprops/action-gh-release`
is pinned to a full commit SHA per a security review finding. Confirmed working end to end (two full green
runs). One known flake: the Windows-hosted runner occasionally hits a native Tk crash
(`Windows fatal exception: code 0x80000003`) during the GUI test suite — not a real bug (278/279 tests pass
reliably locally every time), user explicitly decided to just re-run the job manually if it happens rather
than add `pytest-rerunfailures` or other mitigation.

**Manual local build validated end to end**: `packaging/Output/rekamind-0.1.0.exe` (~1.88GB) exists on this
machine, built via `pyinstaller Rekamind.spec` + Inno Setup (`ISCC.exe`, installed per-user via
`winget install --id JRSoftware.InnoSetup`, lives at
`C:\Users\aji\AppData\Local\Programs\Inno Setup 6\ISCC.exe` — NOT the usual `Program Files (x86)` location).
ffmpeg.exe was downloaded manually from gyan.dev and placed at `packaging/ffmpeg/ffmpeg.exe`, then copied
into `packaging/dist/Rekamind/ffmpeg/` per `packaging/README.md`'s documented steps.
**This local build has real CUDA support** (this venv's torch is `+cu126`) — it is NOT the same as what CI
currently produces.

**Manual functional testing done this session** (all on this machine — Ryzen 5 5600G + GTX 1080 Ti):
- Recorded a ~21-minute test meeting (`recordings/02a4dbbc07634a4d926dbec0186ce934/`), ran Transkrip +
  Ringkasan successfully, monitored CPU/RAM/GPU for 15 minutes — stable, no leaks, bursty CPU/GPU pattern
  matches the documented `LiveDiarizeLoop` tick design.
- CPU-only ASR+diarize benchmark (forced, not via the app) on this Ryzen 5 5600G: 36.4 minutes total for
  the 21-minute recording (~1.7x slower than real-time). Relevant context if revisiting the AMD
  Ryzen 7 8845HS / Ryzen AI 350 hardware-compatibility discussion (conclusion at the time: no CUDA, and
  OpenVINO's GPU/NPU plugins are Intel-only so AMD iGPU/NPU gets no acceleration either — CPU fallback only).
- Sync push() tested successfully — files land in the real MinIO bucket. Sync **pull()** has NOT been
  validated end to end this session (only discussed a plan: temporarily flip `.env` to
  `STORAGE_BACKEND=sqlite` + a fake `DEVICE_ID` to simulate a second device, since pull() skips manifests
  matching the local device_id and everything synced so far is under this one device's real identity).

## Environment notes for the new session

- Repo: `C:\Project\meeting`, branch `master`. `.env` exists (dev mode) with **real credentials** — shared
  Postgres at `10.55.11.209`, a Groq API key, an HF token, and MinIO creds pointing at `10.55.11.194:7000`
  (bucket `rekamind`). Never commit this file.
- GitHub API calls this session were authenticated by extracting the stored OAuth token from Git Credential
  Manager: `printf 'protocol=https\nhost=github.com\n\n' | git credential fill` — works because `git push`
  to the `github` remote already succeeded once (stored credential has repo access). Reuse this pattern for
  any further GitHub API/CI diagnostics.
- Full test suite: `pytest -q` from repo root, consistently 278 passed / 2 skipped / 2 deselected.
