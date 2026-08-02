# Resume prompt — Rekamind v0.1.0, Machine B (Intel laptop) first run

Paste this whole file as your first message when starting a new session **on the Intel laptop**
(Core Ultra 7 155H, Meteor Lake, Arc iGPU + NPU). This machine has never run Rekamind before —
that is the entire job for this session.

## Status

`v0.1.0` is tagged and pushed to both remotes (GitLab `origin` + GitHub `github`, kept in sync).
Everything on Machine A (desktop, Ryzen 5 5600G + GTX 1080 Ti) is done and verified there: CUDA
reproducibility, the OpenVINO 30-second-truncation bug quarantine, the `model_cache` CWD-relative
fix, and the RAM/startup work (idle RSS 924MB → 99MB, `_models` idle-unload, live-diarizer worker
teardown). See `CHANGELOG.md` for the full release summary and `CLAUDE.md` for architecture — both
are current as of this tag; don't re-derive what they already answer.

## What to do, in order

### 1. Clone and install

```bash
git clone https://github.com/handokoaji/rekamind.git
cd rekamind

# CPU wheel, not CUDA -- this laptop has no NVIDIA GPU.
pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

If the repo is already here, `git pull` instead and confirm `git log --oneline -1` matches the
desktop's (should be at or past the `v0.1.0` tag).

### 2. Configure `.env`

```bash
cp .env.example .env
```

Fill in the **same shared credentials** Machine A uses (Postgres host, Groq key, HF token, MinIO)
— ask for these if you don't have them; they're real secrets, never commit `.env`. Leave
`DEVICE_ID`/`DEVICE_LABEL` blank: they default to this machine's hostname in dev mode
(`app/config.py::Settings._default_device_identity`), which is exactly what you want — it gives
this machine a distinct identity from Machine A for the sync test in step 5.

### 3. First launch

```bash
python -m app.main
```

Confirm the window opens. Check `%LOCALAPPDATA%\MeetingRecorder\logs\app.log` (or console output)
for which backend `detect_backend()` picked — it **must say `cpu`**, not `openvino` (auto-selecting
openvino was deliberately disabled, see `CHANGELOG.md`'s "Changed" section). Don't force
`ASR_BACKEND_OVERRIDE=openvino` for a real meeting yet — it will correctly `raise
NotImplementedError` on anything over 30 seconds now (no chunking loop exists), instead of
silently truncating like it used to.

### 4. Record and process a real test meeting

Record a few minutes with "Mulai Rekam" / "Stop Rekam", then run Transkrip and Ringkasan from
Riwayat. Confirm the transcript, speaker labels, and generated `mom.docx` all look right. Time
Transkrip and watch Task Manager — CPU-only large-v3 + pyannote measured **~2529s (42 min) for a
21-minute recording** on a Ryzen 5 5600G (no AVX-512). This Meteor Lake CPU has AVX-VNNI and more
cores, so it should be faster — but measure it, don't assume (`CHANGELOG.md`/git history has the
79/21 vs 60/40 ASR/diarization split that CPU forcing produced on the desktop, for comparison).

### 5. Validate sync `pull()` — never done before, now finally possible

This needed two real machines with two real hostnames (two real `device_id`s), which is why it was
never tested until now:

1. On Machine A (desktop): record a small meeting, then click "Sync Sekarang".
2. On Machine B (this laptop): click "Sync Sekarang" and confirm Machine A's meeting appears in
   Riwayat with the correct transcript/summary, and that "Unduh Docx" fetches `mom.docx` on demand.
3. Confirm the ownership UI: for Machine A's meeting (not owned by B), Transkrip/Ringkasan/Coba
   Lagi should be **hidden**; Hapus/Lihat Transkrip/Unduh Docx should stay visible
   (`app/ui/history_view.py::_update_action_panel`).

### 6. Open decisions

- **Rename `_APP_DIR_NAME`?** `app/settings_store.py`'s `_APP_DIR_NAME = "MeetingRecorder"` is
  deliberately unrenamed — changing it to `"Rekamind"` now would orphan Machine A's existing local
  data (DB, recordings, config, logs). Not a bug, a decision to make once both machines are in use.
- **Is OpenVINO's proper chunking fix worth building?** The CPU-forced benchmark on Machine A found
  diarization has a hard ~1000s floor regardless of ASR backend — pyannote scales ~24.9× worse onto
  CPU than ctranslate2's int8 ASR does (~9.8×) — so even a perfect OpenVINO ASR could only ever
  remove the ASR portion of the total time here, never the diarization portion. Get a real
  ASR-vs-diarization split on *this* hardware (`ASR_BACKEND_OVERRIDE=cpu` first, since openvino
  currently hard-fails past 30s) before deciding it's worth the rewrite.

## Reference

- Full architecture: `CLAUDE.md`.
- Release history: `CHANGELOG.md`.
- Hardware conclusions that don't need re-litigating: OpenVINO's GPU/NPU plugins are Intel-only
  (AMD gets CPU only, full stop, without a new DirectML/Vulkan backend); pyannote diarization has
  no non-CUDA accelerated path anywhere (the credible fix would be porting it to ONNX — a separate
  project, output quality unverified against torch pyannote); using the 155H's NPU and iGPU
  together for one Whisper decode isn't realistic (autoregressive single-stream decode, and the NPU
  has restricted dynamic-shape support that the KV-cache decoder needs).
- `.env` on this machine, once created, has real credentials — never commit it.
- GitHub API calls, if needed, can be authenticated via the stored Git Credential Manager token:
  `printf 'protocol=https\nhost=github.com\n\n' | git credential fill`.
- Full test suite: `pytest -q` from repo root (hardware-/postgres-marked tests deselected by
  default, see `pytest.ini`). A known pre-existing flake on machines with a real display: rapid
  `tk.Tk()` creation/destruction across many tests occasionally raises a Tcl init-file error on one
  random test — always passes re-run alone, not a regression, don't chase it.

## Appendix — packaging reference data (parked, not abandoned)

Installer/packaging work is parked: it optimises bytes-shipped-once, which doesn't move RAM,
startup time, or throughput — the things this release actually prioritized. If it's ever resumed,
this is real measured data from that investigation, kept so nobody re-derives it:

| Item | Size |
|---|---|
| `torch` in a CUDA venv | 4225 MB, of which `torch/lib` = 4074 MB |
| CUDA-only DLLs inside that | ~3.77 GB (`torch_cuda` 1049, `cublasLt` 532, `cudnn_engines_precompiled` 514, `cusparse` 288, `cudnn_adv` 282, `cufft` 277, `cusolver`+`cusolverMg` 223, `cudnn_ops` 127, `cublas` 105, `curand` 63, rest ~300) |
| `openvino` | 235 MB (+ `openvino_tokenizers` 4 MB) |
| `ctranslate2` | 63 MB |
| PyInstaller dist, torch included | 4816 MB → 1880 MB installer (39% compression, actually built) |
| PyInstaller dist, torch excluded | 1021 MB, of which 299 MB is `torch/lib` dragged in by `torchaudio` |
| torch cu126 cp311 wheel (CDN) | 2474 MB |
| torch cpu cp311 wheel (CDN) | 116 MB |

Two facts worth keeping:

- `Rekamind.spec` does `collect_all("torch")`, which puts torch's `.py` files into the **PYZ
  inside the exe**, where PyInstaller's frozen importer finds them before anything on `sys.path`.
  Removing `_internal/torch` from the dist alone is not enough to unbundle torch;
  `excludes=["torch"]` is also required — and even then `collect_all("torchaudio")` drags 299 MB of
  `torch_cpu.dll`/`c10.dll` back into `_internal/torch/lib`, which has to be deleted explicitly.
- cuBLAS/cuDNN are **not** shipped as separate `nvidia-*` packages here. They live in `torch/lib`,
  and ctranslate2 finds them there because `import torch` calls `os.add_dll_directory()` on that
  folder. The CUDA torch install is what enables GPU ASR *and* GPU diarization — no separate CUDA
  Toolkit is needed for end users, only the NVIDIA driver.
- Inno Setup on the desktop: `ISCC.exe` lives at
  `C:\Users\aji\AppData\Local\Programs\Inno Setup 6\ISCC.exe` (per-user winget install, **not** the
  usual `Program Files (x86)` path). It's 6.3+, so `CreateDownloadPage`/`Extract7ZipArchive` are
  both available as built-ins if a download-at-install-time scheme is ever revisited.
