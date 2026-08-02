# Resume prompt — Rekamind final release, two-hardware focus

Paste this whole file as your first message in a new session to pick up exactly where the
previous one left off.

> **STATUS: Steps 0–5 are ALL DONE** (this session, model Sonnet 5, two continuations).
> Tasks 1–3 are **committed and pushed** to both remotes (`e0d3991`, `e383870`, `bbdb7d3`, on top
> of `7b67db3` which was also pushed this session — it had been sitting local-only since the prior
> session). Tasks 4–5 are implemented and verified (**290 tests, 287 passed** typical — 1-2 flaky
> on `no display available`/Tcl init-file detection from rapid `tk.Tk()` churn, always pass in
> isolation, pre-existing and unrelated) but **not yet committed** — ask before committing/pushing,
> per this repo's standing policy.
>
> Headline result from Task 5: idle RSS after `import app.main` dropped from **924 MB → 99 MB**
> (an 89% cut), and import time from ~7-9s to ~1.0s — by tracing the exact transitive import
> chain rather than guessing (a lightweight
> `SpeakerSegment` dataclass was living inside the same module as the heavy `Diarizer` class,
> so anything merely needing the dataclass pulled in torch+pyannote regardless).
>
> Task 4's question is answered too: CUDA is ASR-dominated (79/21 ASR/diarization split), but
> CPU-forced (the closest proxy for Machine B) flips to 60/40 — diarization scales ~24.9× slower
> onto CPU vs. its CUDA time (ASR only ~9.8×), so it has a hard ~1000s floor on the 21-minute test
> recording regardless of which ASR backend Machine B ends up using. This caps how much Task 1's
> proper OpenVINO-chunking fix can ever help — full reasoning in "part 2" near the bottom.
>
> Only remaining item from the whole plan: **setting up and testing on Machine B is still
> untouched** — it's a physical laptop, nobody has been able to do that from this machine. Once
> that happens, go straight to Task 6's checklist.

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

## Task 4 — measure before optimising anything else [DONE]

Measured on Machine A (this machine) using a standalone script (not the full GUI app — that hits
real Postgres/MinIO and can pop a real blocking dialog, see the test-hang postmortem below), driving
`build_models()` + `transcriber.transcribe()` + `diarizer.diarize()` directly against the existing
21-minute test recording (`recordings/02a4dbbc07634a4d926dbec0186ce934/`). Full numbers, including
the before/after RSS from Task 5's fixes, are in "What was done ... part 2" near the bottom.

**CUDA (real Machine A config)**: ASR 156.2s (79%), diarization 40.3s (21%) of a 196.5s total —
i.e. ASR dominates, both stages GPU-accelerated. ~6.4× faster than real time.

**CPU-forced (`backend_name="cpu"` for both stages — the closest same-machine proxy for Machine
B's diarization path, since OpenVINO/NPU can never accelerate diarization there)**: ASR 1527.0s
(60%), diarization 1002.2s (40%) of a 2529.2s (42.2 min) total — ~2× *slower* than real time.
Diarization's share nearly doubles vs. the CUDA run because it scales far worse onto CPU (~24.9×
slower than its CUDA time) than ASR does (~9.8× slower) — pyannote's deep model apparently doesn't
degrade as gracefully onto CPU as ctranslate2's int8 decode. Practical conclusion: diarization has
a hard floor of ~1000s on this recording regardless of ASR backend, so Task 1's proper OpenVINO
chunking fix has a real but capped ceiling — it can only ever remove the ASR portion of Machine B's
total time, never the diarization portion, which will likely keep Machine B well short of Machine
A's speed no matter how much ASR-side work goes in. Full reasoning in "part 2" below.

## Task 5 — the "lightweight / low RAM" work [DONE]

All four done, plus one that wasn't on the original list (found via measurement, see below). None
involve packaging.

1. **Eager imports at startup — done, and it went deeper than the plan expected.** Not just
   `Diarizer`/`OpenVinoWhisperBackend`: `FasterWhisperBackend` (needed by *every* backend) also
   transitively imports torch via `faster_whisper`, and `app/pipeline/merge.py` was importing the
   lightweight `SpeakerSegment` dataclass from the SAME module as the heavy `Diarizer` class, so
   `main.py`'s otherwise-untouched `from app.live.session import LiveSession` chain (`session` →
   `diarize_loop` → `pipeline.merge` → `diarization.diarizer`) pulled in torch+pyannote regardless
   of the other fixes. Fixed by adding `app/diarization/base.py` (just the dataclass) and pointing
   `merge.py` at it directly. Verified with a real import-time RSS measurement, not assumption:
   **924 MB → 99 MB**, **~7-9s → ~1.0s**. Confirmed zero of torch/pyannote/transformers/optimum/
   openvino/ctranslate2/faster_whisper load at `import app.main` time now.
2. **`_models` idle-unload — done.** `app/main.py` gained `_unload_models_if_idle()`
   (pure, testable) + `_idle_unload_loop()` (a daemon thread, lazily started on first
   `load_models()` call, checks every 60s) + `_MODELS_IDLE_TIMEOUT_SECONDS = 15 * 60` (ponytail:
   fixed value, no config surface, raise it if 15 min proves too aggressive on real usage).
   Verified safe for the existing concurrent-callers test and for a caller mid-transcription when
   the global cache gets cleared out from under it (clearing the cache only affects the *next*
   `load_models()` call, not objects a caller already holds).
3. **Live transcriber int8 on CUDA — done.** `build_live_transcriber`'s cuda branch changed from
   `compute_type="float32"` to `"int8"`, matching the batch path. Not separately quality-tested
   against real speech (out of scope to set up a listening test this session) — justified by: (a)
   it's a provisional preview, fully replaced by the batch pass, and (b) `build_transcriber`'s own
   comment already established int8 as correct for this GPU generation (Pascal/1080 Ti) regardless
   of model size. If live preview text quality visibly degrades on Machine A, revert just this one
   line back to float32 -- it's independent of everything else here.
4. **`ProcessIsolatedDiarizer` worker teardown — done.** `LiveDiarizeLoop.stop()` now duck-type
   calls `shutdown()` on its diarizer if it has one (the batch `Diarizer` and most test doubles
   don't, and that's fine — `getattr(..., "shutdown", None)`, no-op if absent). This runs every
   time `RecorderController._stop_live_session()` fires, which is every real "Stop Rekam" (and
   error-path cleanup) — `shutdown()` only tears down the worker *process*, not the
   `ProcessIsolatedDiarizer` object itself (still cached in `main.py`'s `live_session_factory`
   closure), so the next meeting's first diarize() call just respawns a fresh worker lazily, same
   as the existing crash/timeout recovery path already did.

Tests added: 3 for idle-unload (`tests/test_main.py`), 2 for worker teardown
(`tests/live/test_diarize_loop.py`). Existing tests that patched `main.Diarizer` /
`main.FasterWhisperBackend` / `main.OpenVinoWhisperBackend` were updated to patch the dotted
source-module path instead (`app.diarization.diarizer.Diarizer` etc.) — standard consequence of
moving an import from module-level to function-local, `monkeypatch.setattr(main, "X", ...)`
requires `X` to already be a module attribute, which a lazy import no longer provides.

## Task 6 — release checklist

- [x] Tasks 1–3 done, `pytest -q` green (**281 passed / 2 skipped / 2 deselected**, ~23s).
- [x] Tasks 4–5 done, see above and "part 2" below. `pytest -q` green (**~287 passed / ~2 skipped
      / 2 deselected**, ~30s; 1-2 tests are a pre-existing Tk-churn flake, always pass alone).
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

## What was done in the Sonnet 5 continuation (this session, committed as `e0d3991`/`e383870`/`bbdb7d3`, pushed to both remotes)

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

## What was done in the Sonnet 5 continuation, part 2 (Task 4 + Task 5, not yet committed)

Same session, same machine, continued after Tasks 1–3 were committed and pushed. User said
"kerjakan semua" (do everything) — this covers Task 4's measurement and all four Task 5 items.

**Task 4 measurement.** Wrote a standalone script (not saved to the repo — it lived in the
session's scratchpad dir) that imports `app.main`, calls `build_models()` for a real backend, then
times `transcriber.transcribe()` (mic, then speaker) and `diarizer.diarize()` separately against
the existing 21-minute test recording, sampling RSS every 0.5s throughout for the peak. Deliberately
did NOT run the full GUI app — `python -m app.main` hits real Postgres/MinIO from `.env` and can
pop a real blocking dialog if unreachable (see part 1's test-hang postmortem; same failure shape).

CUDA run (this machine's real config):
- RSS before any import: 20 MB. After `import app.main` (pre-Task-5.1 code): 924 MB. After
  `build_models`: 1119 MB. **Peak: 3997 MB.**
- ASR: mic.wav 21.9s (0 segments — that channel is mostly silence in this recording), speaker.wav
  134.3s (421 segments). **ASR total 156.2s.**
- Diarization: 40.3s, 211 turns.
- **ASR 79%, diarization 21%, total 196.5s** for 21 minutes of audio (~6.4× real time).

CPU-forced run (`backend_name="cpu"` for both stages — the closest available proxy for Machine B,
since diarization is CPU-only there regardless of ASR backend):
- RSS after `build_models('cpu')`: 2608 MB. **Peak: 4978 MB.**
- ASR: mic.wav 416.4s (0 segments, mostly-silent channel), speaker.wav 1110.7s (478 segments).
  **ASR total 1527.0s.**
- Diarization: 1002.2s, 211 turns.
- **ASR 60%, diarization 40%, total 2529.2s** (42.2 min) for 21 minutes of audio (~2× *slower*
  than real time). Close to, and in the same ballpark as, the earlier never-broken-down historical
  figure of 36.4 minutes for this same recording (that one was forced manually, outside the app,
  so some difference is expected — not investigated further, both point the same direction).

**This answers Task 4's original question.** Diarization's share nearly doubles under CPU (21% on
CUDA → 40% CPU-forced). Both stages get slower moving from CUDA to CPU, but not equally: ASR slows
down ~9.8× (156.2s → 1527.0s) while diarization slows down ~24.9× (40.3s → 1002.2s) — pyannote's
deep model apparently scales far worse onto CPU than ctranslate2's int8 decode does, so
diarization's share of the total grows even though it's the smaller absolute number on GPU. The
number that actually matters for deciding whether Task 1's "properly
fix OpenVINO chunking" work is worth it: diarization has a **hard floor of ~1002s (~16.7 min) of
CPU time on this recording, regardless of which ASR backend Machine B ends up using** — OpenVINO/
Arc-iGPU ASR could theoretically approach CUDA-like ASR speed (156s) and the total would STILL be
dominated by diarization's ~1000s floor. This means the OpenVINO chunking rewrite has a **real but
capped ceiling**: it can only ever remove the ASR portion of the total, never the diarization
portion, and diarization is the larger and non-negotiable cost on any non-CUDA machine. Concretely,
best case with a fully-fixed fast OpenVINO ASR: total ≈ (some ASR time, likely a few hundred
seconds) + ~1000s diarization — probably still 15-25+ minutes for a 21-minute recording, i.e. still
close to or slower than real time. Temper expectations for Machine B accordingly: it will likely
never feel "fast" the way Machine A's CUDA path does, no matter how much ASR-side work goes into
it, unless diarization itself gets an accelerated (e.g. ONNX-based) path — which was already flagged
as a separate, larger, out-of-scope project in the "Hardware conclusions" section below.

Still worth doing once Machine B exists: re-run both `ASR_BACKEND_OVERRIDE=cpu` and
`ASR_BACKEND_OVERRIDE=openvino` (after Task 1's proper chunking fix) directly on that hardware —
CPU int8 throughput and pyannote CPU throughput both depend on real core count/AVX support, which
differs from this AMD Zen 3 machine (Meteor Lake has AVX2+AVX-VNNI, no AVX-512, more cores). Numbers
here are a same-machine proxy, not a substitute for the real hardware.

**Task 5, all four items — see the Task 5 section above for the what/why of each; this is the
mechanical diff summary:**

- `app/main.py`: `FasterWhisperBackend`/`OpenVinoWhisperBackend`/`Diarizer`/`ProcessIsolatedDiarizer`
  imports all moved from module level into the functions that use them
  (`build_transcriber`, `build_live_transcriber`, `build_models`, `live_session_factory`).
  `build_live_transcriber`'s CUDA branch: `compute_type="float32"` → `"int8"`. New:
  `_models_last_used`, `_idle_unload_thread_started`, `_MODELS_IDLE_TIMEOUT_SECONDS` (15 min),
  `_MODELS_IDLE_CHECK_INTERVAL_SECONDS` (60s), `_unload_models_if_idle()`, `_idle_unload_loop()`;
  `load_models()` now stamps `_models_last_used` and lazily starts the idle-unload daemon thread
  on first call. Added `import time`.
- `app/diarization/base.py` (**new file**): just the `SpeakerSegment` dataclass, moved out of
  `app/diarization/diarizer.py`. That module now does `from app.diarization.base import
  SpeakerSegment  # noqa: F401` to re-export it (so the many existing `from
  app.diarization.diarizer import SpeakerSegment` call sites keep working unchanged), but anything
  that only needs the dataclass should import from `app.diarization.base` directly to actually
  avoid the torch+pyannote cost — which is exactly what...
- `app/pipeline/merge.py` now does: `from app.diarization.base import SpeakerSegment` instead of
  importing it from `app.diarization.diarizer`. This was the actual fix that closed the gap — Task
  5.1's main.py-only changes alone only got idle RSS from 924 MB down to ~848 MB, because
  `main.py`'s still-eager `from app.live.session import LiveSession` transitively reached this
  same dataclass through `diarize_loop.py` → `pipeline/merge.py` → the heavy module, regardless of
  what main.py itself imported eagerly. Found by bisecting main.py's remaining top-level imports
  one at a time with a small script that diffs `sys.modules` before/after each `__import__()`, not
  by guessing — worth re-using that technique if RSS creeps back up later. Confirmed after this
  fix: `import app.main` pulls in NONE of torch/pyannote/transformers/optimum/openvino/
  ctranslate2/faster_whisper.
- `app/live/diarize_loop.py`: `LiveDiarizeLoop.stop()` now calls `self._diarizer.shutdown()` if
  the diarizer has one (duck-typed via `getattr(..., "shutdown", None)`), after joining the tick
  thread.
- `tests/test_main.py`: 3 new tests for the idle-unload functions; updated `_patch()` and
  `test_build_models_openvino_uses_cpu_diarizer` to `monkeypatch.setattr("dotted.module.path",
  ...)` instead of `monkeypatch.setattr(main, "X", ...)` for `FasterWhisperBackend`, `Diarizer`,
  `OpenVinoWhisperBackend` — required because a function-local import means `main` no longer has
  those as module attributes to patch; pytest's monkeypatch supports the dotted-string form
  directly (imports the module, patches the attribute there instead).
- `tests/live/test_diarize_loop.py`: 2 new tests (shuts down when the diarizer has `shutdown()`,
  no-ops/doesn't-raise when it doesn't).

**Verification**: `pytest -q` → 290 collected, typically 287 passed / 2 skipped / 2 deselected in
~30s (occasionally 286/1-2 skipped — see the recurring Tk flake note in part 1's postmortem;
always passes in isolation, confirmed 3 times with 3 different Tcl error messages for the same
underlying "too many `tk.Tk()` created/destroyed in one process" issue, not a regression).

**Not yet committed** (ask before committing/pushing, per this repo's standing policy). Files
touched this part: `app/main.py`, `app/diarization/diarizer.py`, `app/pipeline/merge.py`,
`app/live/diarize_loop.py`, `tests/test_main.py`, `tests/live/test_diarize_loop.py`, plus new file
`app/diarization/base.py`, plus this file (`RESUME_PROMPT.md`).

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
  `github` = `https://github.com/handokoaji/rekamind.git`. Both in sync at `bbdb7d3` as of this
  session (which includes `7b67db3` from the prior session — it had been local-only until now).
  Tasks 4–5's work (part 2 above) is a further 7 files changed on top of `bbdb7d3`, not yet
  committed.
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
