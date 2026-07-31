import threading
import time
from types import SimpleNamespace

import sys

import app.main as main


def test_check_ffmpeg_available_true_when_on_path(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: "C:/ffmpeg/ffmpeg.exe")
    assert main.check_ffmpeg_available() is True


def test_check_ffmpeg_available_false_when_missing(monkeypatch, capsys):
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    assert main.check_ffmpeg_available() is False
    assert "ffmpeg" in capsys.readouterr().err.lower()


class _FakeDiarizer:
    def __init__(self, hf_token=None, device=None):
        self.device = device


def _patch(monkeypatch, cuda_ok: bool):
    calls = []

    class _FakeWhisper:
        def __init__(self, device=None, compute_type=None):
            calls.append(device)
            if device is None and not cuda_ok:
                raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(main, "FasterWhisperBackend", _FakeWhisper)
    monkeypatch.setattr(main, "Diarizer", _FakeDiarizer)
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


def test_build_models_openvino_uses_cpu_diarizer(monkeypatch):
    _patch(monkeypatch, cuda_ok=True)
    monkeypatch.setattr(main, "OpenVinoWhisperBackend", lambda: object())
    settings = SimpleNamespace(hf_token="t", groq_api_key="k")
    _, diarizer, _ = main.build_models("openvino", settings)
    assert diarizer.device == "cpu"
