# Resume prompt — Rekamind final release, two-hardware focus

Paste this whole file as your first message in a new session to pick up exactly where the
previous one left off.

> **STATUS: Step 0 and Tasks 1–3 are DONE** (this session, model Sonnet 5) and verified —
> `pytest -q` is **281 passed, 2 skipped, 2 deselected in ~23s**. Not yet committed; 9 files
> changed, see "What was done in the Sonnet 5 continuation" near the bottom for the exact diff.
> Also fixed in passing: a pre-existing test-isolation bug in `tests/test_main.py` that pops a
> REAL blocking Tk dialog and hangs the whole suite indefinitely on any dev-mode checkout (i.e.
> both target machines) — see that section for details, it cost ~15 minutes of wall-clock to
> find and is worth reading before touching that file again.
> Next up: Task 4 (measurement) and Task 5 (RAM/startup work), or set up
> Machine B if you'd rather validate Tasks 1–3 on real hardware first.

## Scope decision (read this first)

**Installer/packaging work is PARKED.** After measuring real sizes and weighing four different
bundling strategies, the conclusion was that installer work optimises the one thing that matters
least (bytes shipped once) and does nothing for RAM, startup time, or throughput. It is deferred
until after this release.

The target for this release is **two specific machines**, both running from source (dev mode,
`.env` present, `python -m app.main`). No installer is required to call this version done.

| | Machine A (already in use) | Machine B (never used yet) |
|---|---|---|
| CPU | AMD Ryzen 5 5600G (Zen 3, no AVX-512) | Intel Core Ultra 7 155H (Meteor Lake) |
| GPU | NVIDIA GTX 1080 Ti (Pascal, sm_61, 11GB) | Intel Arc iGPU + NPU (AI Boost) |
| `detect_backend()` picks | `"cuda"` | `"openvino"` ← **broken, see Task 1** |
| torch build needed | `2.13.0+cu126` | `2.13.0+cpu` |
| Status | works end to end | **has never been run once** |

Note on Machine B expectations: Meteor Lake has **no AVX-512** (Intel removed it from consumer
parts), only AVX2 + AVX-VNNI. ctranslate2's int8 path uses AVX-VNNI, so CPU throughput there
should be respectable but is unmeasured. Do not assume it beats or loses to the 5600G number
below without measuring.

## Step 0 — discard the parked installer work

Four files carry **uncommitted** edits from the abandoned slim-installer experiment. Revert them
before doing anything else:

```
git checkout -- packaging/Rekamind.spec packaging/installer.iss \
                packaging/README.md .github/workflows/build-installer.yml
```

That returns them to commit `7b67db3`, which is the correct state — `7b67db3` is *this session's*
work and must be kept (see "Already done" below). Also delete
`packaging/build/` and `packaging/dist/` if present; they are stale artifacts from a test build
where torch was excluded from the bundle.

---

## Task 1 — HIGH: the OpenVINO backend silently truncates every recording to 30 seconds

This is the single most important finding. It has never fired because Machine A always resolves to
`"cuda"` and Machine B has never been used. It will fire on the **first real use** of the laptop.

**Verified, not inferred.** Whisper's feature extractor truncates to a fixed 30-second window and
`OpenVinoWhisperBackend.transcribe()` has no chunking loop around it:

```python
>>> audio = np.zeros(16000*60*21, dtype=np.float32)     # 21 minutes
>>> WhisperProcessor.from_pretrained('openai/whisper-small')(
...     audio, sampling_rate=16000, return_tensors='pt').input_features.shape
(1, 80, 3000)                                            # 3000 frames = 30 seconds
```

`app/asr/openvino_backend.py:42-49` has two defects:

1. **Truncation** — 20.5 of 21 minutes are discarded with no error, no warning, no log line.
2. **No timestamps** — it returns a single `TranscriptSegmentResult(start_ms=0,
   end_ms=<full duration>)`. `app/pipeline/merge.py::merge_segments` assigns a speaker by
   maximum time overlap, so one giant segment collapses the entire meeting onto one speaker.

Failure chain, all silent: batch transcript is the authoritative one and fully replaces the live
preview → `summarize_and_export` sends a 30-second transcript to Groq → the MoM docx comes out
looking complete and confident but covering half a minute of a one-hour meeting.

The **live** pipeline is largely spared by accident: `SpeechSegmenter` (silero-vad) emits short
utterances that rarely exceed 30 seconds. It is the batch path — the one users trust — that breaks.

### Fix now (small, closes the risk)

- `app/asr/detect.py::detect_backend()` must stop auto-selecting `"openvino"`. Fall through to
  `"cpu"` instead, so Machine B lands on the ctranslate2 path that Machine A has already proven.
  Keep `ASR_BACKEND_OVERRIDE=openvino` working so the backend stays reachable for development.
  Leave a comment naming this as a deliberate quarantine, not an oversight.
- `OpenVinoWhisperBackend.transcribe()` should raise a clear error on audio longer than 30 seconds
  rather than truncate. If someone forces the backend, it must fail loudly.
- Tests for both. `tests/asr/` already exists.

### Fix properly — LATER, gated on measurement (see Task 4)

Rewriting the backend means a 30-second chunking loop with `return_timestamps=True`, mapping each
chunk's timestamps back to absolute offsets so `merge_segments` gets real boundaries. Do **not**
start this until the Machine B benchmark shows the Arc iGPU actually beats ctranslate2 on CPU
there. If it does not, delete the backend instead of maintaining it.

Also unverified and worth checking during that work: whether
`OVModelForSpeechSeq2Seq.generate(..., language=...)` even accepts the `language` kwarg the code
passes — that is a `transformers` `WhisperForConditionalGeneration` feature and may raise on the
optimum-intel wrapper.

## Task 2 — MEDIUM: `model_cache` is CWD-relative

`app/asr/openvino_backend.py:29`:

```python
def __init__(self, model_size="large-v3", device="GPU", cache_dir=Path("./model_cache")):
```

Same bug class as the `logs/` directory fixed in `82ed1c0`. Converting whisper-large-v3 to
OpenVINO IR takes many minutes and a lot of RAM; the cache exists so it happens once. Relative to
CWD it may be written somewhere unexpected, or fail outright, and then be redone every launch.

Route it through `app/settings_store.py` to `%LOCALAPPDATA%\MeetingRecorder\model_cache`, matching
how `sqlite_db_path` and the logs directory already work. This only ever bites Intel users — i.e.
exactly Machine B. The user has already approved this fix.

## Task 3 — reproducible setup for both machines

The current `.venv` has `torch==2.13.0+cu126` installed **manually and undocumented**; it is not
reproducible from a clean checkout. `pyproject.toml` cannot express a per-package index URL, so
this has to be a documented explicit step.

Document in the top-level `README.md` (not `packaging/README.md` — that one is parked):

```bash
# Machine A — desktop, GTX 1080 Ti
pip install torch==2.13.0+cu126 --index-url https://download.pytorch.org/whl/cu126
pip install -e .

# Machine B — laptop, Core Ultra 7 155H
pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

Install torch **first** either way; `pip install -e .` then sees the requirement satisfied and
leaves the build in place. Verified live URLs and sizes: cu126 cp311 wheel = 2474 MB, cpu cp311
wheel = 116 MB.

Each machine needs its own `.env` (copy `.env.example`). Do **not** copy Machine A's `.env`
wholesale — it contains real credentials and should not travel further than necessary.
`device_id`/`device_label` default to `socket.gethostname()` in dev mode (commit `b765c8d`), so
the two machines get distinct device identities automatically with no manual configuration.

## Task 4 — measure before optimising anything else

Three numbers are missing and every remaining decision depends on them. None have ever been taken.

1. **RSS at idle**, right after startup with no meeting loaded — measures the cost of eager imports.
2. **RSS at peak** during a batch Transkrip.
3. **ASR vs diarization time split** within a batch run.

Number 3 is the important one. The only benchmark that exists is *36.4 minutes total for a
21-minute recording* (~1.7× slower than real time), taken with **ctranslate2 on CPU on the Ryzen 5
5600G**, forced manually rather than through the app. It has never been broken down into ASR time
vs diarization time.

Why it decides things: on Machine B, **pyannote diarization always runs on CPU**. OpenVINO cannot
run it, and neither can the NPU — it is torch, and there is no Intel-accelerated path for it.
So if diarization turns out to be the majority of those 36 minutes, then accelerating ASR onto the
Arc iGPU (Task 1's proper fix) buys a small fraction of the total and is not worth the rewrite.
Amdahl's law decides this, not preference.

Then run the same benchmark on Machine B, both ways — `ASR_BACKEND_OVERRIDE=cpu` vs
`ASR_BACKEND_OVERRIDE=openvino` — once Task 1's proper fix exists to make the comparison honest.

## Task 5 — the "lightweight / low RAM" work

These serve the stated goal directly, and none of them involve packaging. Ordered by expected
payoff, but re-rank after Task 4's numbers land.

1. **Eager imports at startup.** `app/main.py` imports `Diarizer` and `OpenVinoWhisperBackend` at
   module level. Through them, every launch on every machine loads `torch`, `pyannote.audio`,
   `transformers`, `optimum.intel.openvino`, and `openvino` — including on Machine A, which will
   never touch the OpenVINO stack. Make the backend imports lazy, inside
   `build_transcriber`/`build_models`.
2. **`_models` is never unloaded.** The lazy singleton in `main.py` holds large-v3 int8 + pyannote
   from the first Transkrip click until the app exits. Consider releasing it after an idle
   timeout. Note the existing comment explaining why the lock is there (concurrent
   Transkrip/Ringkasan is allowed per spec §6) — any unload logic has to respect that.
3. **`build_live_transcriber` uses `compute_type="float32"` on CUDA** (`app/main.py:89`) while the
   batch path already uses `int8`. Roughly 4× the VRAM for a preview that is thrown away and
   replaced by the batch transcript. Check whether int8 is good enough for the live preview.
4. **`ProcessIsolatedDiarizer` is a second full pyannote copy in a separate OS process.** The
   isolation is deliberate and documented (pyannote/CUDA has crashed the host process natively),
   so do not remove it — but consider tearing the worker down when recording stops rather than
   keeping it resident for the rest of the app run. This matters much more on a laptop.

## Task 6 — release checklist

- [x] Tasks 1–3 done, `pytest -q` green (**281 passed / 2 skipped / 2 deselected**, ~23s).
- [ ] Machine B set up and a real meeting recorded, transcribed, and summarised on it end to end.
- [ ] **Validate sync `pull()`** — never done. This is now finally possible without tricks: two
      real machines with two real hostnames means two real `device_id`s. Record on A, push, then
      pull on B and confirm the meeting materialises with its transcript and that "Unduh Docx"
      fetches `mom.docx` on demand. `pull()` skips manifests matching the local device_id, which is
      why this could never be tested with only one machine.
- [ ] Confirm the Riwayat ownership UI behaves on B: Transkrip/Ringkasan/Coba Lagi hidden for
      meetings owned by A, while Hapus/Lihat Transkrip/Unduh Docx stay available
      (`app/ui/history_view.py::_update_action_panel`).
- [ ] Decide whether `_APP_DIR_NAME = "MeetingRecorder"` in `app/settings_store.py` gets renamed to
      Rekamind. Still deliberately unrenamed — changing it orphans existing local data (DB,
      recordings, config.json, logs) on Machine A. Open decision, not a bug.
- [ ] Tag `v0.1.0` and push to both remotes.

---

## What was done in the Sonnet 5 continuation (this session, not yet committed)

Step 0 and Tasks 1–3 from the plan above, all done and verified:

- **Step 0**: reverted the 4 parked installer files to `7b67db3`, deleted stale
  `packaging/build/`/`packaging/dist/`.
- **Task 1**: `app/asr/detect.py::detect_backend()` no longer auto-selects `"openvino"` — falls
  through to `"cpu"` instead, quarantine comment explains why, still reachable via
  `ASR_BACKEND_OVERRIDE=openvino`. Deleted `_openvino_gpu_or_npu_available()` since nothing calls
  it anymore (dead code, not kept "for later" — git history has it if needed). In
  `app/asr/openvino_backend.py`, `transcribe()` now raises `NotImplementedError` for audio over
  `MAX_TRANSCRIBE_SECONDS` (30.0) instead of silently truncating. Tests updated in
  `tests/asr/test_detect.py` (removed the now-nonexistent openvino-fallback test, added one
  asserting openvino is never auto-picked) and `tests/asr/test_openvino_backend.py` (+2: raises
  past the limit, allows exactly at the limit).
- **Task 2**: added `app/settings_store.py::model_cache_dir_path()` → `%LOCALAPPDATA%\
  MeetingRecorder\model_cache`, same pattern as `sqlite_db_path`/`recordings_dir_path`/the logs
  dir. `OpenVinoWhisperBackend.__init__`'s `cache_dir` param defaults to `None` and resolves to
  that path (both call sites in `app/main.py` already call it with no `cache_dir` arg, so no
  other changes needed there). Test added in `tests/test_settings_store.py`.
- **Task 3**: `README.md` Quickstart now has the per-machine torch install commands (cu126 vs
  cpu, install torch first), plus a note on `device_id` defaulting to hostname. The feature-list
  bullet about automatic backend detection was corrected to say CUDA/CPU only, pointing at
  `ASR_BACKEND_OVERRIDE` for OpenVINO. (`packaging/README.md` was deliberately left untouched —
  parked with the rest of packaging.)

**Bug found and fixed along the way, unrelated to Tasks 1–3 but directly blocking them:**
`tests/test_main.py::test_handle_startup_db_error_returns_false_on_no` only mocked
`messagebox.askyesno`, never `is_dev_mode`. `_handle_startup_db_error` branches on `is_dev_mode()`
*before* it would ever reach the askyesno call — and on any dev checkout (real `.env` present,
which is the actual setup on both target machines) that resolves to the **real**
`messagebox.showerror`, which — since this machine has a real display and Tk is genuinely
available — opens an actual blocking Windows dialog titled "Rekamind - Error" and hangs pytest
indefinitely (not busy-hung — near-zero CPU, waiting on a human to click OK). The test's own
assertions still happened to hold either way (both branches return `False` and never call
`SetupWizard`), so it silently "passed" for anyone patient enough to click through it, which is
presumably why it was never caught: it only actually blocks when someone runs the *full* suite
unattended on a dev checkout. This is likely why the previously-recorded 46–90s full-suite timings
elsewhere in this doc were sometimes way off — this test was silently eating minutes depending on
who ran it and whether they were watching the screen. Fixed by pinning
`monkeypatch.setattr(main, "is_dev_mode", lambda: False)`, matching the two sibling tests that
already do this correctly (`test_handle_startup_db_error_reopens_wizard_on_yes` and
`..._as_toplevel_on_existing_root`). If a real dialog like this ever appears again during a test
run: it'll be a top-level window owned by the pytest process, findable via `user32.dll`
`EnumWindows` + `GetWindowThreadProcessId` filtered to that PID, closable by finding the `Button`
child titled "OK" and posting `BM_CLICK` (`0x00F5`) to it — no need to kill the process and lose
whatever else was mid-run.

**Result**: `pytest -q` → `281 passed, 2 skipped, 2 deselected, 3 warnings in ~23s`. The 3
warnings are `PytestUnhandledThreadExceptionWarning: RuntimeError: Event loop is closed` from
`aiosqlite`'s background worker thread outliving the event loop in `tests/ui/test_controller.py`
— pre-existing, unrelated to anything touched this session, does not fail the suite. Left alone;
out of scope for the two-hardware focus.

## What was already done this session (don't redo)

**Commit `7b67db3` — "fix: make CUDA support reproducible and stop the diarizer crashing without it".**
Two halves, both keep:

- `app/main.py::diarizer_device()` — new helper. `build_models()` used to compute the diarizer's
  device *outside* its `try/except`, so on a machine with CUDA-capable ctranslate2 but a CPU-only
  torch wheel, `Diarizer.__init__`'s `.to(torch.device("cuda"))` raised
  `Torch not compiled with CUDA enabled` and killed the entire Transkrip action — not a silent
  fallback, a hard failure. `detect_backend()` asks ctranslate2, which carries its own CUDA runtime
  independent of torch's, so the two really can disagree. ASR now stays on CUDA while only the
  diarizer drops to CPU. The live `ProcessIsolatedDiarizer` had the identical bug at the identical
  expression and now shares the helper.
- CI (`.github/workflows/build-installer.yml`) installs `torch==2.13.0+cu126` before
  `pip install -e .`, and `packaging/README.md` documents the same as step 0. Every CI-built
  installer before this shipped with zero CUDA support.
- One new test: `test_build_models_keeps_asr_on_cuda_but_diarizes_on_cpu_when_torch_lacks_cuda`.

**Analysis done, no code changed** — findings are recorded above as Tasks 1–5. In particular the
30-second truncation proof (Task 1) and the CWD-relative `model_cache` (Task 2) both came out of
this analysis and are the reason the installer work was parked.

**Everything from the previous session** (all committed and pushed, both remotes in sync as of
`083d93a`): Pengaturan dialog MinIO/device_label fields + wizard `pack()` ordering (`6e5ba94`);
`MINIO_ENDPOINT` scheme parsing (`6f75175`); `device_id`/`device_label` hostname defaults
(`b765c8d`); seven external code-review findings — `mom.docx` written to the wrong directory
(`831fda5`), CWD-relative `logs/` (`82ed1c0`), deleted meetings resurrected by sync, fixed with a
`Meeting.deleted_at` tombstone (`9b06eb5`), Pengaturan + startup-DB-error recovery being silent
no-ops in dev mode (`e03919e`), non-numeric Postgres port crashing the wizard (`68ae8ed`),
possibly-unbound `message` in the sync worker (`5d1ea22`); CI fixes (`1b66340`, `f4fab06`); and the
full packaging rebrand to Rekamind (`083d93a`).

## Reference data measured this session

Kept because it is real measurement, not estimate — useful whenever packaging is revisited.

| Item | Size |
|---|---|
| `torch` in the venv (cu126) | 4225 MB, of which `torch/lib` = 4074 MB |
| CUDA-only DLLs inside that | ~3.77 GB (`torch_cuda` 1049, `cublasLt` 532, `cudnn_engines_precompiled` 514, `cusparse` 288, `cudnn_adv` 282, `cufft` 277, `cusolver`+`cusolverMg` 223, `cudnn_ops` 127, `cublas` 105, `curand` 63, rest ~300) |
| `torch_cpu.dll` | 305 MB |
| `openvino` | 235 MB (+ `openvino_tokenizers` 4 MB) |
| `ctranslate2` | 63 MB |
| `onnxruntime` | 45 MB |
| PyInstaller dist, torch included | 4816 MB → 1880 MB installer (39% ratio, actually built) |
| PyInstaller dist, torch excluded | 1021 MB, of which 299 MB is `torch/lib` dragged in by `torchaudio` |
| torch cu126 cp311 wheel (CDN) | 2474 MB |
| torch cpu cp311 wheel (CDN) | 116 MB |

Two facts worth keeping from the packaging investigation, so nobody re-derives them:

- `Rekamind.spec` does `collect_all("torch")`, which puts torch's `.py` files into the **PYZ inside
  the exe**, where PyInstaller's frozen importer finds them before anything on `sys.path`. Removing
  `_internal/torch` from the dist is therefore not enough to unbundle torch; `excludes=["torch"]`
  is also required — and even then `collect_all("torchaudio")` drags 299 MB of `torch_cpu.dll` /
  `c10.dll` back into `_internal/torch/lib`, which has to be deleted explicitly.
- cuBLAS/cuDNN are **not** shipped as separate `nvidia-*` packages here. They live in `torch/lib`,
  and **ctranslate2 finds them there** because `import torch` calls `os.add_dll_directory()` on
  that folder. So the CUDA torch install is what enables GPU ASR *and* GPU diarization; there is
  no separate CUDA Toolkit requirement for end users, only the NVIDIA driver.

## Hardware conclusions (settled, don't re-litigate)

- **OpenVINO's GPU and NPU plugins are Intel-only.** AMD Radeon iGPUs (780M on 8845HS, 860M on
  Ryzen AI 350) and the XDNA NPU are invisible to `ov.Core().available_devices`. AMD machines
  therefore get ctranslate2 on CPU, full stop, unless a DirectML or Vulkan ASR backend is built.
- **pyannote diarization has no non-CUDA accelerated path.** Not OpenVINO, not NPU, not DirectML in
  any mature form. On every non-NVIDIA machine diarization is CPU-bound, and it sets the ceiling.
  The one credible way out would be porting diarization to ONNX (pyannote segmentation + speaker
  embedding models exist in ONNX form, e.g. as used by sherpa-onnx), which would serve Intel and
  AMD with one piece of work — a separate project, and its output quality would need validating
  against torch pyannote first.
- **Using the 155H's NPU and iGPU together is not realistic.** OpenVINO's `MULTI`/`AUTO` split
  parallel inference *requests*; a Whisper decode is a single autoregressive latency-bound stream.
  The NPU also has restricted dynamic-shape support, which the KV-cache decoder needs.
- **1080 Ti is Pascal (sm_61)** — no fp16 tensor cores, and faster-whisper's float16 misbehaves on
  that generation. `build_transcriber` already correctly picks `int8` (CUDA DP4A path, supported
  from 6.1). Do not "upgrade" it to float16.
- PyTorch's CUDA wheels are compiled for a per-build list of GPU architectures, and Pascal has been
  progressively dropped as the CUDA toolchain advanced. If NVIDIA support is ever widened beyond
  the 1080 Ti, check whether one wheel can still cover both Pascal and Blackwell — it likely
  cannot, and that would split any future CUDA build in two.

## Environment notes

- Repo: `C:\Project\meeting`, branch `master`. `.env` exists (dev mode) with **real credentials** —
  shared Postgres at `10.55.11.209`, a Groq API key, an HF token, and MinIO at `10.55.11.194:7000`
  (bucket `rekamind`). Never commit this file.
- Remotes: `origin` = GitLab `git.dev.ugm.ac.id/aksi_riset/meeting.git`,
  `github` = `https://github.com/handokoaji/rekamind.git`. `7b67db3` is committed locally but
  **not yet pushed to either remote**.
- GitHub API calls can be authenticated by pulling the stored OAuth token out of Git Credential
  Manager: `printf 'protocol=https\nhost=github.com\n\n' | git credential fill`.
- Full test suite: `pytest -q` from repo root. Hardware- and postgres-marked tests are deselected
  by default (see `pytest.ini`).
- Inno Setup, if packaging is ever resumed: `ISCC.exe` lives at
  `C:\Users\aji\AppData\Local\Programs\Inno Setup 6\ISCC.exe` (per-user install via winget, **not**
  the usual `Program Files (x86)` path). It is 6.3+, so `CreateDownloadPage` and
  `Extract7ZipArchive` are both available as built-ins.
- Existing test recording: `recordings/02a4dbbc07634a4d926dbec0186ce934/` (~21 minutes, already
  transcribed and summarised successfully on Machine A). Reuse it for the Task 4 benchmarks so the
  numbers stay comparable to the 36.4-minute CPU figure.
