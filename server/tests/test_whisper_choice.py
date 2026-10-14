import pytest

from rekamind_server.engines.whisper import FasterWhisperTranscriber, choose_compute


@pytest.mark.parametrize("device,supported,expected", [
    ("cuda", {"float32", "int8", "int8_float32", "float16", "int8_float16"}, "float16"),           # Turing and newer
    ("cuda", {"float32", "int8", "int8_float32"}, "int8"),                                        # Pascal: 4 GB, faster than float32
    ("cuda", {"float32"}, "float32"),
    ("cpu", {"float32", "int8"}, "int8"),
])
def test_compute_type_follows_what_the_gpu_runs_well(device, supported, expected):
    assert choose_compute(device, supported) == expected


def test_an_out_of_memory_gpu_retries_lighter_and_finally_on_the_cpu(monkeypatch):
    import sys
    import types

    attempts = []

    class Seg:
        start, end, text, no_speech_prob = 0.0, 1.0, " halo ", 0.0

    class FakeModel:
        def __init__(self, name, device, compute_type):
            attempts.append((device, compute_type))
            self.device, self.compute = device, compute_type

        def transcribe(self, path, **kw):
            if self.device == "cuda":
                raise RuntimeError("CUDA failed with error out of memory")
            return iter([Seg()]), None

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    ct = types.ModuleType("ctranslate2")
    ct.get_cuda_device_count = lambda: 1
    ct.get_supported_compute_types = lambda d: ["float16", "int8", "float32"] if d == "cuda" else ["int8", "float32"]
    monkeypatch.setitem(sys.modules, "ctranslate2", ct)

    t = FasterWhisperTranscriber("tiny")
    out = t.transcribe("x.wav", "id")
    assert [s.text for s in out] == ["halo"]
    assert attempts == [("cuda", "float16"), ("cuda", "int8"), ("cpu", "int8")]


def test_other_runtime_errors_are_not_swallowed(monkeypatch):
    import sys
    import types

    class FakeModel:
        def __init__(self, *a, **k): ...
        def transcribe(self, *a, **k):
            raise RuntimeError("corrupt audio")

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    ct = types.ModuleType("ctranslate2")
    ct.get_cuda_device_count = lambda: 0
    ct.get_supported_compute_types = lambda d: ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", ct)
    with pytest.raises(RuntimeError, match="corrupt"):
        FasterWhisperTranscriber("tiny").transcribe("x.wav", "id")
