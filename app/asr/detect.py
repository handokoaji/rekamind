def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
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
