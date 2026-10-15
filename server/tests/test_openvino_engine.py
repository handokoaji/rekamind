"""OpenVINO / Intel GPU engine: logic tested with fakes (the real runtime needs the optimum-intel stack and a model)."""
import json
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from rekamind_server import enginepack
from rekamind_server.config import Settings
from rekamind_server.engines import openvino as ov
from rekamind_server.engines.registry import use_openvino


def write_wav(path: Path, seconds: float, amp: float = 0.2, rate: int = 16000) -> Path:
    n = int(seconds * rate)
    t = np.arange(n) / rate
    data = (amp * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path


# ---- helpers -------------------------------------------------------------------------------------------------
def test_model_ids_and_cache_dir(monkeypatch, tmp_path):
    assert ov.model_id("large-v3") == "openai/whisper-large-v3"
    assert ov.model_id("distil-large-v3") == "distil-whisper/distil-large-v3"
    assert ov.model_id("someone/custom") == "someone/custom"
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path))
    assert ov.ir_dir("large-v3") == tmp_path / "openvino-models" / "openai--whisper-large-v3-ov"


def test_windows_cover_audio_in_30s_steps():
    n = int(75 * 16000)
    w = ov.windows(n)
    assert w == [(0, 480000), (480000, 960000), (960000, n)]
    assert ov.windows(0) == []


def test_silence_detection():
    assert ov.is_silent(np.zeros(16000, dtype=np.float32))
    assert ov.is_silent(np.array([], dtype=np.float32))
    assert not ov.is_silent((0.1 * np.sin(np.arange(16000))).astype(np.float32))


def test_load_audio_mixes_down_and_resamples(tmp_path):
    p = tmp_path / "a.wav"
    n = 48000
    stereo = np.stack([np.sin(np.arange(n) / 20), np.sin(np.arange(n) / 20)], axis=1)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(48000)
        w.writeframes((stereo * 20000).astype("<i2").tobytes())
    a = ov.load_audio(p)
    assert a.ndim == 1 and abs(len(a) - 16000) <= 1 and a.dtype == np.float32


# ---- transcriber with a fake optimum/transformers --------------------------------------------------------------
class FakeProcessor:
    class tokenizer:  # noqa: N801
        @staticmethod
        def decode(ids, skip_special_tokens=True, output_offsets=False):
            return {"text": "x", "offsets": [{"text": " halo dunia", "timestamp": (0.0, 2.0)},
                                              {"text": " apa kabar", "timestamp": (2.0, None)},
                                              {"text": "  ", "timestamp": (3.0, 4.0)}]}

    def __call__(self, chunk, sampling_rate, return_tensors):
        return types.SimpleNamespace(input_features=chunk)

    def batch_decode(self, ids, skip_special_tokens=True):
        return [" teks satu jendela "]

    @classmethod
    def from_pretrained(cls, *a, **k):
        return cls()


class FakeModel:
    calls: list[dict] = []
    fail_devices: set[str] = set()
    timestamps_ok = True

    @classmethod
    def from_pretrained(cls, path, device="CPU", **k):
        if device in cls.fail_devices:
            raise RuntimeError(f"no {device}")
        m = cls()
        m.device = device
        return m

    def generate(self, feats, **kw):
        FakeModel.calls.append(kw)
        if kw.get("return_timestamps") and not FakeModel.timestamps_ok:
            raise TypeError("unexpected keyword return_timestamps")
        return [[1, 2, 3]]


@pytest.fixture
def fake_stack(monkeypatch, tmp_path):
    FakeModel.calls, FakeModel.fail_devices, FakeModel.timestamps_ok = [], set(), True
    ovm = types.ModuleType("optimum.intel.openvino")
    ovm.OVModelForSpeechSeq2Seq = FakeModel
    tr = types.ModuleType("transformers")
    tr.WhisperProcessor = FakeProcessor
    mods = {"optimum": types.ModuleType("optimum"), "optimum.intel": types.ModuleType("optimum.intel"),
            "optimum.intel.openvino": ovm, "transformers": tr}
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(ov, "prepare_model", lambda name, log=print: tmp_path)
    return tmp_path


def test_transcribe_uses_timestamp_offsets_and_skips_silent_windows(fake_stack, tmp_path):
    # 35 s: a tone for the first 30 s window and silence in the second -> only the first is decoded
    wav = tmp_path / "m.wav"
    n = 35 * 16000
    data = np.zeros(n, dtype="<i2")
    data[: 30 * 16000] = (0.2 * np.sin(np.arange(30 * 16000) / 5) * 32767).astype("<i2")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(data.tobytes())
    t = ov.OpenVinoTranscriber("small", "GPU")
    segs = t.transcribe(wav, "id")
    assert len(FakeModel.calls) == 1 and FakeModel.calls[0]["language"] == "id" and FakeModel.calls[0]["return_timestamps"] is True
    assert [(s.start_ms, s.end_ms, s.text) for s in segs] == [(0, 2000, "halo dunia"), (2000, 30000, "apa kabar")]
    assert t.active_device == "GPU"


def test_second_window_offsets_are_absolute(fake_stack, tmp_path):
    wav = write_wav(tmp_path / "long.wav", 40)
    segs = ov.OpenVinoTranscriber("small", "GPU").transcribe(wav, "id")
    assert segs[2].start_ms == 30000 and segs[2].text == "halo dunia"  # first segment of the 2nd window


def test_falls_back_to_one_segment_per_window_without_timestamp_support(fake_stack, tmp_path):
    FakeModel.timestamps_ok = False
    wav = write_wav(tmp_path / "m.wav", 40)
    t = ov.OpenVinoTranscriber("small", "GPU")
    segs = t.transcribe(wav, "id")
    assert [(s.start_ms, s.end_ms, s.text) for s in segs] == [(0, 30000, "teks satu jendela"), (30000, 40000, "teks satu jendela")]
    # the unsupported call is attempted once, not once per window
    assert sum(1 for c in FakeModel.calls if c.get("return_timestamps")) == 1


def test_gpu_failure_falls_back_to_cpu(fake_stack, tmp_path):
    FakeModel.fail_devices = {"GPU"}
    t = ov.OpenVinoTranscriber("small", "GPU")
    t.transcribe(write_wav(tmp_path / "m.wav", 5), "id")
    assert t.active_device == "CPU"


def test_total_failure_is_a_clear_error(fake_stack, tmp_path):
    FakeModel.fail_devices = {"GPU", "CPU"}
    with pytest.raises(RuntimeError, match="OpenVINO tidak bisa memuat model"):
        ov.OpenVinoTranscriber("small", "GPU").transcribe(write_wav(tmp_path / "m.wav", 5), "id")


def test_release_drops_the_model(fake_stack, tmp_path):
    t = ov.OpenVinoTranscriber("small", "GPU")
    t.transcribe(write_wav(tmp_path / "m.wav", 5), "id")
    t.release()
    assert t._model is None and t._processor is None


# ---- selection, pip, status --------------------------------------------------------------------------------------
def test_registry_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path))
    assert use_openvino(Settings(whisper_device="intel")) is True
    assert use_openvino(Settings(whisper_device="cuda")) is False
    assert use_openvino(Settings(whisper_device="cpu")) is False
    assert use_openvino(Settings(whisper_device="auto")) is False  # no pack installed
    pack = tmp_path / "engine-pack"
    pack.mkdir()
    (pack / "installed.json").write_text(json.dumps({"kind": "openvino"}))
    assert use_openvino(Settings(whisper_device="auto")) is True
    (pack / "installed.json").write_text(json.dumps({"kind": "cuda"}))
    assert use_openvino(Settings(whisper_device="auto")) is False


def test_pip_args_for_openvino_use_the_openvino_stack_not_faster_whisper(tmp_path):
    a = enginepack.pip_args("openvino", tmp_path, False)
    assert "openvino>=2025.0" in a and "torch" in a
    assert not any("faster-whisper" in x for x in a)
    assert "--extra-index-url" in a  # torch comes from the CPU wheel index
    assert "pyannote.audio>=4.0" in enginepack.pip_args("openvino", tmp_path, True)
    with pytest.raises(ValueError):
        enginepack.pip_args("rocm", tmp_path, False)


def test_status_reports_kind_and_gpus(monkeypatch, tmp_path):
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(enginepack, "detect_gpus", lambda: [{"vendor": "intel", "name": "Intel(R) Arc(TM) Graphics"}])
    pack = tmp_path / "engine-pack"
    pack.mkdir()
    (pack / "installed.json").write_text(json.dumps({"kind": "openvino", "diarize": False}))
    s = enginepack.status()
    assert s["kind"] == "openvino" and s["gpus"][0]["vendor"] == "intel"


def test_detect_gpus_never_raises_and_reads_linux_vendor_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    drm = tmp_path / "drm" / "card0" / "device"
    drm.mkdir(parents=True)
    (drm / "vendor").write_text("0x8086\n")
    real_path = enginepack.Path
    monkeypatch.setattr(enginepack, "Path", lambda p: real_path(str(p).replace("/sys/class/drm", str(tmp_path / "drm"))))
    assert enginepack._detect_gpus() == [{"vendor": "intel", "name": "intel 0x8086"}]
    monkeypatch.setattr(enginepack, "Path", lambda p: (_ for _ in ()).throw(OSError("boom")))
    assert enginepack._detect_gpus() == []


def test_gpu_detection_is_cached_on_disk_so_status_stays_fast(monkeypatch, tmp_path):
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(enginepack, "_detect_gpus", lambda: calls.append(1) or [{"vendor": "amd", "name": "AMD Radeon(TM) 860M Graphics"}])
    enginepack.detect_gpus.cache_clear()
    assert enginepack.detect_gpus()[0]["vendor"] == "amd"
    enginepack.detect_gpus.cache_clear()  # a new process: only the file remembers
    assert enginepack.detect_gpus()[0]["name"].startswith("AMD Radeon") and len(calls) == 1
    # an old cache is refreshed
    f = tmp_path / "gpus.json"
    f.write_text(json.dumps({"platform": sys.platform, "at": 0, "gpus": []}))
    enginepack.detect_gpus.cache_clear()
    assert enginepack.detect_gpus()[0]["vendor"] == "amd" and len(calls) == 2
    enginepack.detect_gpus.cache_clear()
