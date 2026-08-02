class UnsupportedHardwareError(RuntimeError):
    """Tidak ada backend ASR (GPU maupun CPU) yang bisa jalan di perangkat ini."""


def _ctranslate2_importable() -> bool:
    try:
        import ctranslate2  # noqa: F401
        return True
    except ImportError:
        return False


def _cuda_available() -> bool:
    """faster-whisper runs on ctranslate2, not torch — checking torch.cuda
    here would report no-GPU on a machine with CUDA-capable ctranslate2 but
    a CPU-only torch wheel (torch is only pulled in transitively, by the
    diarizer)."""
    if not _ctranslate2_importable():
        return False
    import ctranslate2
    return ctranslate2.get_cuda_device_count() > 0


def detect_backend(override: str = "") -> str:
    if override:
        return override
    if _cuda_available():
        return "cuda"
    # "openvino" is deliberately NOT auto-selected here even when a GPU/NPU is
    # available: OpenVinoWhisperBackend has no chunking loop and hard-fails
    # past 30 seconds of audio (see app.asr.openvino_backend), so picking it
    # automatically would break every real meeting on Intel hardware. Still
    # reachable via ASR_BACKEND_OVERRIDE=openvino for development. Remove this
    # quarantine once that backend supports chunking (RESUME_PROMPT.md Task 1).
    if _ctranslate2_importable():
        return "cpu"
    raise UnsupportedHardwareError(
        "Perangkat ini tidak mendukung transkripsi audio (GPU tidak "
        "terdeteksi dan CPU tidak sanggup menjalankan mesin ASR). "
        "Aplikasi tidak bisa dijalankan di perangkat ini."
    )
