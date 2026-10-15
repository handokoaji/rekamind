"""CPU and NVIDIA (faster-whisper) behaviour must be untouched by the OpenVINO / Vulkan engines."""
import json
from pathlib import Path

import pytest

from rekamind_server import enginepack
from rekamind_server.config import Settings
from rekamind_server.engines.registry import build_engines, use_openvino, use_vulkan
from rekamind_server.engines.whisper import FasterWhisperTranscriber, choose_compute


def _marker(data_dir: Path, kind: str | None) -> None:
    pack = data_dir / "engine-pack"
    pack.mkdir(parents=True, exist_ok=True)
    if kind:
        (pack / "installed.json").write_text(json.dumps({"kind": kind, "diarize": False}))


@pytest.mark.parametrize("kind", [None, "cpu", "cuda"])
@pytest.mark.parametrize("device", ["auto", "cuda", "cpu"])
def test_cpu_and_nvidia_setups_still_use_faster_whisper(monkeypatch, tmp_path, kind, device):
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path))
    _marker(tmp_path, kind)
    s = Settings(engines="local", whisper_device=device)
    assert not use_openvino(s) and not use_vulkan(s)
    e = build_engines(s)
    assert isinstance(e.transcriber, FasterWhisperTranscriber)
    assert e.description["transcriber"].startswith("faster-whisper")


@pytest.mark.parametrize("kind,expected_extra", [("cpu", False), ("cuda", False)])
def test_pip_install_arguments_for_cpu_and_cuda_are_unchanged(tmp_path, kind, expected_extra):
    a = enginepack.pip_args(kind, tmp_path, False)
    assert "faster-whisper>=1.0" in a and "av>=12,<17" in a
    assert not any(x in a for x in ("openvino>=2025.0", "torch"))
    assert ("--find-links" in a) is expected_extra  # torch's index only when speaker separation is added
    cuda_libs = {"nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"}
    assert (cuda_libs <= set(a)) is (kind == "cuda")
    with_pyannote = enginepack.pip_args(kind, tmp_path, True)
    assert "pyannote.audio>=4.0" in with_pyannote and "--find-links" in with_pyannote and "--extra-index-url" not in with_pyannote


def test_status_and_check_for_cpu_cuda_markers_use_the_original_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(enginepack, "detect_gpus", lambda: [])
    for kind in ("cpu", "cuda"):
        _marker(tmp_path, kind)
        assert enginepack.status()["kind"] == kind
        # check() must not take the OpenVINO / Vulkan branches: without faster-whisper installed it reports an
        # import error from the original path, not a missing whisper-cli / OpenVINO message.
        got = enginepack.check()
        assert "whisper-cli" not in (got.get("error") or "") and "openvino" not in (got.get("error") or "").lower()


def test_unknown_install_kind_is_rejected_and_known_ones_listed(tmp_path):
    assert enginepack.KINDS == ("cpu", "cuda", "openvino", "vulkan")
    with pytest.raises(ValueError):
        enginepack.pip_args("rocm", tmp_path, False)


def test_nvidia_compute_choice_is_unchanged():
    assert choose_compute("cuda", {"float16", "int8"}) == "float16"
    assert choose_compute("cuda", {"int8", "int8_float32"}) == "int8"
    assert choose_compute("cpu", {"float16"}) == "int8"
