from types import SimpleNamespace

import app.main as main


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


def test_build_models_openvino_uses_cpu_diarizer(monkeypatch):
    _patch(monkeypatch, cuda_ok=True)
    monkeypatch.setattr(main, "OpenVinoWhisperBackend", lambda: object())
    settings = SimpleNamespace(hf_token="t", groq_api_key="k")
    _, diarizer, _ = main.build_models("openvino", settings)
    assert diarizer.device == "cpu"
