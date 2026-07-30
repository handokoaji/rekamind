from unittest.mock import MagicMock

from app.asr import detect


def test_cuda_available_uses_ctranslate2_device_count(monkeypatch):
    fake_ct2 = MagicMock()
    fake_ct2.get_cuda_device_count.return_value = 1
    monkeypatch.setitem(__import__("sys").modules, "ctranslate2", fake_ct2)
    assert detect._cuda_available() is True


def test_cuda_available_false_when_no_devices(monkeypatch):
    fake_ct2 = MagicMock()
    fake_ct2.get_cuda_device_count.return_value = 0
    monkeypatch.setitem(__import__("sys").modules, "ctranslate2", fake_ct2)
    assert detect._cuda_available() is False


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
