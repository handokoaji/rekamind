import threading
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import MagicMock

import sys

import pytest

import app.main as main
from app.asr.detect import UnsupportedHardwareError


def test_check_ffmpeg_available_true_when_on_path(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: "C:/ffmpeg/ffmpeg.exe")
    assert main.check_ffmpeg_available() is True


def test_check_ffmpeg_available_false_when_missing_shows_install_tutorial(monkeypatch, capsys):
    """A packaged .exe has no console (console=False in the PyInstaller spec),
    so the stderr warning alone is invisible to a real user -- it must also
    surface as a dialog with install steps."""
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    shown = []
    monkeypatch.setattr(main.messagebox, "showwarning", lambda title, msg: shown.append((title, msg)))
    fake_root = MagicMock()
    monkeypatch.setattr(main.tk, "Tk", lambda: fake_root)

    assert main.check_ffmpeg_available() is False

    assert "ffmpeg" in capsys.readouterr().err.lower()
    assert len(shown) == 1
    title, msg = shown[0]
    assert title == "Rekamind"
    assert "winget install ffmpeg" in msg
    fake_root.withdraw.assert_called_once()
    fake_root.destroy.assert_called_once()


class _FakeDiarizer:
    def __init__(self, hf_token=None, device=None):
        self.device = device


def _patch(monkeypatch, cuda_ok: bool, torch_cuda: bool = True):
    calls = []
    monkeypatch.setattr(main, "_torch_has_cuda", lambda: torch_cuda)

    class _FakeWhisper:
        def __init__(self, device=None, compute_type=None):
            calls.append(device)
            if device is None and not cuda_ok:
                raise RuntimeError("CUDA out of memory")

    # FasterWhisperBackend/Diarizer are imported lazily inside build_transcriber()/
    # build_models() now (see app.main), so they're no longer module attributes
    # of `main` to patch there -- patch them where they're actually looked up.
    monkeypatch.setattr("app.asr.cuda_backend.FasterWhisperBackend", _FakeWhisper)
    monkeypatch.setattr("app.diarization.diarizer.Diarizer", _FakeDiarizer)
    monkeypatch.setattr(main, "GroqSummarizer", lambda api_key=None: object())
    return calls


def test_build_models_uses_cuda_for_both_when_backend_loads(monkeypatch):
    _patch(monkeypatch, cuda_ok=True)
    settings = SimpleNamespace(hf_token="t", groq_api_key="k")
    _, diarizer, _ = main.build_models("cuda", settings)
    assert diarizer.device == "cuda"


def test_build_models_falls_back_to_cpu_for_diarizer_too(monkeypatch):
    calls = _patch(monkeypatch, cuda_ok=False)
    settings = SimpleNamespace(hf_token="t", groq_api_key="k")
    _, diarizer, _ = main.build_models("cuda", settings)
    # transcriber retried on CPU...
    assert calls == [None, "cpu"]
    # ...and the diarizer must follow it, not the original "cuda" request.
    assert diarizer.device == "cpu"


def test_build_models_keeps_asr_on_cuda_but_diarizes_on_cpu_when_torch_lacks_cuda(monkeypatch):
    """A CPU-only torch wheel next to a CUDA-capable ctranslate2 (what a plain
    `pip install -e .` produces): .to("cuda") would raise inside pyannote."""
    calls = _patch(monkeypatch, cuda_ok=True, torch_cuda=False)
    settings = SimpleNamespace(hf_token="t", groq_api_key="k")
    _, diarizer, _ = main.build_models("cuda", settings)
    assert calls == [None]  # transcriber still on CUDA, no fallback
    assert diarizer.device == "cpu"


class _FakePyAudioModule:
    """Stands in for pyaudiowpatch; records that the throwaway instance is closed."""
    terminated = []

    class PyAudio:
        def get_default_wasapi_loopback(self):
            return {"defaultSampleRate": 48000.0, "maxInputChannels": 2, "index": 7}

        def terminate(self):
            _FakePyAudioModule.terminated.append(True)


def test_query_loopback_format_reads_native_rate_and_channels(monkeypatch):
    """C1: the live pipeline needs the loopback device's native format, read
    independently of any recorder instance."""
    _FakePyAudioModule.terminated.clear()
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", _FakePyAudioModule)

    assert main.query_loopback_format() == (48000, 2)
    assert _FakePyAudioModule.terminated == [True]  # throwaway instance not leaked


def test_query_loopback_format_terminates_even_on_failure(monkeypatch):
    class _Boom(_FakePyAudioModule):
        class PyAudio:
            def get_default_wasapi_loopback(self):
                raise OSError("no loopback device")

            def terminate(self):
                _FakePyAudioModule.terminated.append(True)

    _FakePyAudioModule.terminated.clear()
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", _Boom)

    try:
        main.query_loopback_format()
        assert False, "expected OSError"
    except OSError:
        pass
    assert _FakePyAudioModule.terminated == [True]


def test_live_models_are_built_lazily_inside_the_live_session_factory():
    """I7/I8: the small live model and the live diarizer must not load before the
    Tkinter window exists, and must be reused across meetings once loaded."""
    import inspect

    source = inspect.getsource(main.main)
    assert source.index("build_live_transcriber(") > source.index("def live_session_factory"), \
        "build_live_transcriber must be called inside live_session_factory, not eagerly"
    assert "nonlocal live_transcriber, live_diarizer" in source, \
        "both the live model and the live diarizer must be cached across meetings"


def test_load_models_builds_only_once_under_concurrent_callers(monkeypatch):
    """spec §6: Transkrip/Ringkasan on two meetings may run at the same time.
    Without a lock both threads see the cache empty and each builds its own
    large-v3 + pyannote pair -- a straight path to CUDA OOM."""
    build_calls = []
    monkeypatch.setattr(main, "_models", None)

    def slow_build(backend_name, settings):
        build_calls.append(backend_name)
        time.sleep(0.2)  # wide enough for the second thread to land inside the race
        return ("transcriber", "diarizer", "summarizer")

    monkeypatch.setattr(main, "build_models", slow_build)

    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(main.load_models("cuda", SimpleNamespace()))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(build_calls) == 1, f"models built {len(build_calls)} times, expected 1"
    assert len(results) == 2
    assert results[0] is results[1], "both threads must share the one cached tuple"

    main._models = None


def test_unload_models_if_idle_frees_them_past_the_timeout(monkeypatch):
    monkeypatch.setattr(main, "_models", ("t", "d", "s"))
    monkeypatch.setattr(main, "_models_last_used", 1000.0)

    unloaded = main._unload_models_if_idle(now=1000.0 + main._MODELS_IDLE_TIMEOUT_SECONDS + 1)

    assert unloaded is True
    assert main._models is None


def test_unload_models_if_idle_is_a_noop_within_the_timeout(monkeypatch):
    monkeypatch.setattr(main, "_models", ("t", "d", "s"))
    monkeypatch.setattr(main, "_models_last_used", 1000.0)

    unloaded = main._unload_models_if_idle(now=1000.0 + main._MODELS_IDLE_TIMEOUT_SECONDS - 1)

    assert unloaded is False
    assert main._models == ("t", "d", "s")


def test_load_models_rebuilds_after_being_unloaded(monkeypatch):
    monkeypatch.setattr(main, "_models", None)
    monkeypatch.setattr(main, "_idle_unload_thread_started", True)  # don't spawn a real thread here
    build_calls = []
    monkeypatch.setattr(main, "build_models", lambda b, s: build_calls.append(1) or ("t", "d", "s"))

    main.load_models("cuda", SimpleNamespace())
    assert len(build_calls) == 1

    main._unload_models_if_idle(now=main._models_last_used + main._MODELS_IDLE_TIMEOUT_SECONDS + 1)
    assert main._models is None

    main.load_models("cuda", SimpleNamespace())
    assert len(build_calls) == 2

    main._models = None


def test_build_models_openvino_uses_cpu_diarizer(monkeypatch):
    _patch(monkeypatch, cuda_ok=True)
    # Also imported lazily now (see build_transcriber's openvino branch).
    monkeypatch.setattr("app.asr.openvino_backend.OpenVinoWhisperBackend", lambda: object())
    settings = SimpleNamespace(hf_token="t", groq_api_key="k")
    _, diarizer, _ = main.build_models("openvino", settings)
    assert diarizer.device == "cpu"


def test_live_session_factory_uses_live_backend_name_independently_of_batch(monkeypatch):
    """The live pipeline must be able to pick a different backend than batch
    (e.g. live="openvino" while batch stays "cuda") -- CUDA/batch must never
    be touched by an override that only targets live_asr_backend_override."""
    import inspect

    source = inspect.getsource(main.main)
    live_factory_start = source.index("def live_session_factory")
    live_factory_source = source[live_factory_start:]

    assert "build_live_transcriber(live_backend_name)" in live_factory_source
    assert "diarizer_device(live_backend_name)" in live_factory_source
    # Batch stays on the plain backend_name, untouched by the live override.
    batch_source = source[:live_factory_start]
    assert "load_models(backend_name, settings)" in batch_source
    assert (
        "live_backend_name = settings.live_asr_backend_override or backend_name" in source
    )


def test_main_shows_wizard_on_first_run_and_reports_cancellation(monkeypatch):
    """Packaged mode, no config.json yet: the wizard must run, and if the
    user closes it without submitting, the gate reports False so main()
    knows not to proceed to creating MainWindow."""
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main, "load_packaged_config", lambda: None)

    wizard_calls = []

    class FakeWizard:
        def __init__(self, parent=None, initial=None):
            wizard_calls.append((parent, initial))

        def run(self):
            return None  # user closed without submitting

    monkeypatch.setattr(main, "SetupWizard", FakeWizard)

    proceed = main.run_first_run_wizard_if_needed()

    assert wizard_calls == [(None, None)]
    assert proceed is False


def test_main_skips_wizard_when_config_already_exists(monkeypatch):
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main, "load_packaged_config", lambda: {"storage_backend": "sqlite"})
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    main.run_first_run_wizard_if_needed()

    assert wizard_calls == []


def test_main_skips_wizard_in_dev_mode(monkeypatch):
    monkeypatch.setattr(main, "is_dev_mode", lambda: True)
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    main.run_first_run_wizard_if_needed()

    assert wizard_calls == []


def test_handle_startup_db_error_reopens_wizard_on_yes(monkeypatch):
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main.messagebox, "askyesno", lambda *a, **k: True)
    saved = []
    monkeypatch.setattr(main, "save_packaged_config", saved.append)

    class FakeWizard:
        def __init__(self, parent=None):
            pass

        def run(self):
            return {"storage_backend": "sqlite"}

    monkeypatch.setattr(main, "SetupWizard", FakeWizard)

    retried = main._handle_startup_db_error(RuntimeError("connection refused"))

    assert retried is True
    assert saved == [{"storage_backend": "sqlite"}]


def test_handle_startup_db_error_reopens_wizard_as_toplevel_on_existing_root(monkeypatch):
    """Regression test: SetupWizard(parent=None) makes SetupWizard create its
    OWN new tk.Tk() root (per its docstring), while _handle_startup_db_error's
    own `root` (used for the messagebox) is still alive at that point -- two
    live Tk() interpreters at once breaks implicit-master widget bindings
    (a StringVar()/etc. created without an explicit master binds to whichever
    interpreter is _default_root, not necessarily the new window's own
    interpreter). SetupWizard must be reopened as a Toplevel on the existing
    root instead, same as every other reopen call site in this codebase."""
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(main, "save_packaged_config", lambda result: None)

    captured_parent = []

    class FakeWizard:
        def __init__(self, parent=None):
            captured_parent.append(parent)

        def run(self):
            return {"storage_backend": "sqlite"}

    monkeypatch.setattr(main, "SetupWizard", FakeWizard)

    main._handle_startup_db_error(RuntimeError("connection refused"))

    assert len(captured_parent) == 1
    assert isinstance(captured_parent[0], tk.Tk)


def test_handle_startup_db_error_shows_env_message_without_wizard_in_dev_mode(monkeypatch):
    """get_settings() always reads .env in dev mode -- reopening the wizard
    would save to config.json (never consulted) and retry with the exact
    same .env-derived settings that just failed, so dev mode must short-
    circuit straight to a message telling the user to edit .env instead."""
    monkeypatch.setattr(main, "is_dev_mode", lambda: True)
    errors_shown = []
    monkeypatch.setattr(main.messagebox, "showerror", lambda title, msg: errors_shown.append((title, msg)))
    asked = []
    monkeypatch.setattr(main.messagebox, "askyesno", lambda *a, **k: asked.append((a, k)) or True)
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    retried = main._handle_startup_db_error(RuntimeError("connection refused"))

    assert retried is False
    assert wizard_calls == []
    assert asked == []
    assert len(errors_shown) == 1
    assert ".env" in errors_shown[0][1]


def test_handle_startup_db_error_returns_false_on_no(monkeypatch):
    """Regression: without pinning is_dev_mode() to False, this test relies on
    whatever .env happens to exist on the machine running it. On a dev
    checkout (both target machines run from source with a real .env) that
    silently takes the OTHER branch and pops a REAL, unmocked messagebox --
    hanging the whole suite until a human clicks it."""
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main.messagebox, "askyesno", lambda *a, **k: False)
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    retried = main._handle_startup_db_error(RuntimeError("connection refused"))

    assert retried is False
    assert wizard_calls == []


def test_main_shows_fatal_error_and_exits_on_unsupported_hardware(monkeypatch):
    def _raise(*args, **kwargs):
        raise UnsupportedHardwareError("Perangkat ini tidak mendukung transkripsi audio.")

    monkeypatch.setattr(main, "detect_backend", _raise)
    error_shown = []
    monkeypatch.setattr(main.messagebox, "showerror", lambda title, msg: error_shown.append((title, msg)))
    window_created = []
    monkeypatch.setattr(main, "MainWindow", lambda *a, **k: window_created.append(True))
    monkeypatch.setattr(main, "run_first_run_wizard_if_needed", lambda: True)

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert error_shown == [("Rekamind", "Perangkat ini tidak mendukung transkripsi audio.")]
    assert window_created == []
    assert exc_info.value.code != 0


def test_main_shows_error_and_returns_when_retried_init_db_also_fails(monkeypatch):
    """Regression test: after the user reconfigures settings via the startup
    error dialog's wizard, the retried asyncio.run(init_db(engine)) had no
    try/except -- a second consecutive DB failure crashed the whole process
    uncaught, invisible in a console-less packaged .exe. It must instead show
    another error dialog and return, same as the UnsupportedHardwareError
    path just above."""
    fake_settings = SimpleNamespace(
        database_url="sqlite+aiosqlite:///:memory:", asr_backend_override="",
        live_asr_backend_override="", hf_token="", groq_api_key="", device_id="d", device_label="l",
    )

    def _fake_get_settings():
        return fake_settings
    _fake_get_settings.cache_clear = lambda: None
    monkeypatch.setattr(main, "get_settings", _fake_get_settings)
    monkeypatch.setattr(main, "run_first_run_wizard_if_needed", lambda: True)
    monkeypatch.setattr(main, "detect_backend", lambda override: "cpu")
    monkeypatch.setattr(main, "check_ffmpeg_available", lambda: True)
    monkeypatch.setattr(main, "make_engine", lambda url: object())

    init_db_calls = []

    def _always_raise(engine):
        init_db_calls.append(engine)
        raise RuntimeError(f"connection refused (attempt {len(init_db_calls)})")

    monkeypatch.setattr(main, "init_db", _always_raise)
    monkeypatch.setattr(main, "_handle_startup_db_error", lambda exc: True)  # user chose to retry

    error_shown = []
    monkeypatch.setattr(main.messagebox, "showerror", lambda title, msg: error_shown.append((title, msg)))
    window_created = []
    monkeypatch.setattr(main, "MainWindow", lambda *a, **k: window_created.append(True))

    main.main()  # must return gracefully, not raise

    assert len(init_db_calls) == 2  # first attempt, then the retry -- both failed
    assert error_shown  # a fatal error dialog was shown instead of crashing uncaught
    assert window_created == []


def test_prepend_bundled_ffmpeg_adds_to_path_when_dir_exists(monkeypatch, tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "MeetingRecorder.exe"))
    monkeypatch.setenv("PATH", "C:\\existing")

    main.prepend_bundled_ffmpeg_to_path()

    assert str(ffmpeg_dir) in main.os.environ["PATH"]
    assert main.os.environ["PATH"].startswith(str(ffmpeg_dir))


def test_prepend_bundled_ffmpeg_no_op_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setenv("PATH", "C:\\existing")

    main.prepend_bundled_ffmpeg_to_path()

    assert main.os.environ["PATH"] == "C:\\existing"


def test_start_update_check_runs_in_background_and_reports_via_callback(monkeypatch):
    monkeypatch.setattr(main.update_check, "check_for_update", lambda cur, url: "0.2.0")
    reported = []

    main._start_update_check(on_update_available=reported.append)

    deadline = time.time() + 2
    while not reported and time.time() < deadline:
        time.sleep(0.01)

    assert reported == ["0.2.0"]


def test_start_update_check_calls_nothing_when_no_update(monkeypatch):
    monkeypatch.setattr(main.update_check, "check_for_update", lambda cur, url: None)
    reported = []

    thread = main._start_update_check(on_update_available=reported.append)
    thread.join(timeout=2)

    assert reported == []


def test_handle_tray_show_pushes_a_live_event_instead_of_calling_after_directly():
    """Regression test for the same crash-risk bug class already fixed twice in
    app/ui/window.py and app/ui/history_view.py: pystray's Icon.run() drives its
    tray callbacks from its OWN background thread (not the Tk main thread), so
    calling root.after(...) directly from show_window()/quit_app() races Tk
    teardown. They must instead hand off through the existing thread-safe
    push_live_event queue, same as every other cross-thread UI update."""
    pushed = []
    window = SimpleNamespace(push_live_event=pushed.append)

    main._handle_tray_show(window)

    assert pushed == [{"type": "show_window"}]


def test_handle_tray_quit_pushes_a_live_event_instead_of_calling_after_directly():
    pushed = []
    window = SimpleNamespace(push_live_event=pushed.append)

    main._handle_tray_quit(window)

    assert pushed == [{"type": "quit_app"}]
