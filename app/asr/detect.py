def _cuda_available() -> bool:
    """faster-whisper runs on ctranslate2, not torch — checking torch.cuda
    here would report no-GPU on a machine with CUDA-capable ctranslate2 but
    a CPU-only torch wheel (torch is only pulled in transitively, by the
    diarizer)."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except ImportError:
        return False


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
    return "cpu"
