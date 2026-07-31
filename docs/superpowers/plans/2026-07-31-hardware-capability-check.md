# GPU/CPU Hardware Capability Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `detect_backend()` explicitly validate that CPU inference can run at all (instead of assuming it always can), and make `main()` refuse to start — with a clear message, before any window exists — on a device where neither GPU nor CPU can run the ASR engine.

**Architecture:** One small addition to the existing `cuda -> openvino -> cpu` cascade in `app/asr/detect.py` (a new `UnsupportedHardwareError` and a shared `_ctranslate2_importable()` check), plus a try/except around the existing `detect_backend()` call site in `app/main.py::main()`.

**Tech Stack:** Python stdlib only (`tkinter.messagebox`, `sys`) — no new dependencies.

## Global Constraints

- Independent of the other plans in this series (storage backend, device identity) — can be implemented in any order relative to them.
- GPU detection logic (`_cuda_available`'s CUDA-device-count check, `_openvino_gpu_or_npu_available`) must not change behavior — only how the CPU fallback is validated.
- Diarization/pyannote/torch stays best-effort — this plan touches ASR backend detection only, never `Diarizer`/pyannote loading.
- Hardware Ultra 7 155H verification is a manual step (Task 3, Step 2) — this plan cannot make an automated test prove real hardware works, only that the existing openvino-detection code path is exercised correctly under mocks.

---

### Task 1: `UnsupportedHardwareError` + CPU validation in `detect_backend()`

**Files:**
- Modify: `app/asr/detect.py`
- Modify: `tests/asr/test_detect.py`

**Interfaces:**
- Produces: `class UnsupportedHardwareError(RuntimeError)`, `_ctranslate2_importable() -> bool`, `detect_backend()` now raises `UnsupportedHardwareError` in the previously-impossible "nothing works" case

- [ ] **Step 1: Write the failing tests**

Append to `tests/asr/test_detect.py`:

```python
import pytest


def test_falls_back_to_cpu_when_ctranslate2_importable_and_nothing_else_available(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: False)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: False)
    monkeypatch.setattr(detect, "_ctranslate2_importable", lambda: True)
    assert detect.detect_backend() == "cpu"


def test_raises_unsupported_hardware_when_nothing_works_at_all(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: False)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: False)
    monkeypatch.setattr(detect, "_ctranslate2_importable", lambda: False)
    with pytest.raises(detect.UnsupportedHardwareError):
        detect.detect_backend()


def test_override_bypasses_the_hardware_check_entirely(monkeypatch):
    monkeypatch.setattr(detect, "_ctranslate2_importable", lambda: False)
    assert detect.detect_backend(override="cpu") == "cpu"


def test_cuda_available_returns_false_when_ctranslate2_not_importable(monkeypatch):
    """_cuda_available must not blow up (or misreport) when ctranslate2 can't
    be imported at all -- it should short-circuit via _ctranslate2_importable
    rather than letting the bare `import ctranslate2` raise uncaught."""
    monkeypatch.setattr(detect, "_ctranslate2_importable", lambda: False)
    assert detect._cuda_available() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/asr/test_detect.py -v`
Expected: FAIL — `detect.UnsupportedHardwareError` and
`detect._ctranslate2_importable` don't exist yet.

- [ ] **Step 3: Write the implementation**

Replace the contents of `app/asr/detect.py` in full:

```python
class UnsupportedHardwareError(RuntimeError):
    """Tidak ada backend ASR (GPU maupun CPU) yang bisa jalan di perangkat ini."""


def _ctranslate2_importable() -> bool:
    try:
        import ctranslate2  # noqa: F401
        return True
    except ImportError:
        return False


def _cuda_available() -> bool:
    """faster-whisper runs on ctranslate2, not torch — checking torch.cuda
    here would report no-GPU on a machine with CUDA-capable ctranslate2 but
    a CPU-only torch wheel (torch is only pulled in transitively, by the
    diarizer)."""
    if not _ctranslate2_importable():
        return False
    import ctranslate2
    return ctranslate2.get_cuda_device_count() > 0


def _openvino_gpu_or_npu_available() -> bool:
    try:
        import openvino as ov
        devices = ov.Core().available_devices
        return any(d.startswith("GPU") or d.startswith("NPU") for d in devices)
    except ImportError:
        return False


def detect_backend(override: str = "") -> str:
    if override:
        return override
    if _cuda_available():
        return "cuda"
    if _openvino_gpu_or_npu_available():
        return "openvino"
    if _ctranslate2_importable():
        return "cpu"
    raise UnsupportedHardwareError(
        "Perangkat ini tidak mendukung transkripsi audio (GPU tidak "
        "terdeteksi dan CPU tidak sanggup menjalankan mesin ASR). "
        "Aplikasi tidak bisa dijalankan di perangkat ini."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/asr/test_detect.py -v`
Expected: all passed (6 existing + 4 new = 10)

- [ ] **Step 5: Commit**

```bash
git add app/asr/detect.py tests/asr/test_detect.py
git commit -m "feat(asr): validate CPU can run ctranslate2 instead of assuming it always can"
```

---

### Task 2: `main()` refuses to start on unsupported hardware

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `app.asr.detect.UnsupportedHardwareError` (Task 1)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
from app.asr.detect import UnsupportedHardwareError


def test_main_shows_fatal_error_and_exits_on_unsupported_hardware(monkeypatch):
    def _raise(*args, **kwargs):
        raise UnsupportedHardwareError("Perangkat ini tidak mendukung transkripsi audio.")

    monkeypatch.setattr(main, "detect_backend", _raise)
    error_shown = []
    monkeypatch.setattr(main.messagebox, "showerror", lambda title, msg: error_shown.append((title, msg)))
    window_created = []
    monkeypatch.setattr(main, "MainWindow", lambda *a, **k: window_created.append(True))

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert error_shown == [("Meeting Recorder", "Perangkat ini tidak mendukung transkripsi audio.")]
    assert window_created == []
    assert exc_info.value.code != 0
```

Add `import pytest` to the top of `tests/test_main.py` if it isn't already
imported (check first).

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main.py -v -k unsupported_hardware`
Expected: FAIL — either `AttributeError` (no `messagebox` on `main`), or
the test hangs/fails trying to reach a real database (today,
`detect_backend()` is called AFTER `make_engine()`/`init_db()` already ran
— see Step 3, this is also being fixed, not just wrapped in place).

- [ ] **Step 3: Write the implementation**

Add `from tkinter import messagebox` to the imports in `app/main.py`
(check first — if a prior plan in this series already added it, don't
duplicate the import).

`detect_backend()` is currently called well into `main()`, AFTER
`make_engine()`/`asyncio.run(init_db(engine))`/`recover_abandoned_meetings`
have already run — meaning by the time hardware gets checked, the app has
already touched the database. That contradicts "no app state exists yet"
(spec §4). Move the check to run immediately after `settings = get_settings()`,
before anything else:

Find the current start of `main()`:

```python
def main() -> None:
    configure_logging()
    settings = get_settings()
    check_ffmpeg_available()
    engine = make_engine(settings.database_url)
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    recovered = asyncio.run(recover_abandoned_meetings(session_factory))
    if recovered:
        logger.info("recovered %d meeting(s) orphaned by a previous crash: %s", len(recovered), recovered)

    backend_name = detect_backend(settings.asr_backend_override)
```

Replace it with:

```python
def main() -> None:
    configure_logging()
    settings = get_settings()
    try:
        backend_name = detect_backend(settings.asr_backend_override)
    except UnsupportedHardwareError as exc:
        messagebox.showerror("Meeting Recorder", str(exc))
        sys.exit(1)
    check_ffmpeg_available()
    engine = make_engine(settings.database_url)
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    recovered = asyncio.run(recover_abandoned_meetings(session_factory))
    if recovered:
        logger.info("recovered %d meeting(s) orphaned by a previous crash: %s", len(recovered), recovered)
```

(`backend_name` is used further down in `main()` exactly as before — only
its assignment moved earlier, its value and later usage are unchanged.)

Add the import at the top of `app/main.py`, alongside the existing
`from app.asr.detect import detect_backend` line:

```python
from app.asr.detect import detect_backend, UnsupportedHardwareError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v -k unsupported_hardware`
Expected: 1 passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat(main): refuse to start with a clear message on unsupported hardware"
```

---

### Task 3: Regression pass + manual hardware verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 2: Manual verification note (cannot be automated)**

This plan's automated tests only prove the *logic* is correct under
mocks — they cannot prove the real `openvino.Core().available_devices`
call actually reports `GPU`/`NPU` entries on an Intel Ultra 7 155H
machine. Per the spec (§5), this must be confirmed by running
`python -c "from app.asr.detect import detect_backend; print(detect_backend())"`
on that hardware once available, and confirming it prints `openvino` (not
`cpu`). Record the result wherever this plan's completion gets tracked —
this step is not satisfied by the automated test suite passing.

- [ ] **Step 3: Commit (if Step 1 or 2 required any fixes)**

```bash
git add -A
git commit -m "fix: address regressions found in full verification pass"
```

(Skip this commit entirely if no changes were needed.)
