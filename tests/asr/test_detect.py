from app.asr import detect


def test_override_takes_priority():
    assert detect.detect_backend(override="cpu") == "cpu"
    assert detect.detect_backend(override="cuda") == "cuda"


def test_falls_back_to_cuda_when_available(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: True)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: False)
    assert detect.detect_backend() == "cuda"


def test_falls_back_to_openvino_when_cuda_missing(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: False)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: True)
    assert detect.detect_backend() == "openvino"


def test_falls_back_to_cpu_when_nothing_available(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: False)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: False)
    assert detect.detect_backend() == "cpu"
