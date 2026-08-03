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
    # "openvino" (iGPU) is deliberately NOT auto-selected here even when the
    # GPU is available: it's only validated on the one Intel machine this
    # project has tested against so far, not "any Intel GPU" in general.
    # Still reachable via ASR_BACKEND_OVERRIDE=openvino (see
    # app.asr.openvino_backend). NPU support was attempted and removed --
    # openvino-genai's NPU pipeline only supports greedy decoding (no beam
    # search, confirmed via "Cannot set a new bigger shape to this tensor"),
    # which reliably drifted real Indonesian speech into English/repeated
    # garbage even with repetition_penalty tuning. Not worth resurrecting
    # without an NPU-side decoding fix upstream.
    if _ctranslate2_importable():
        return "cpu"
    raise UnsupportedHardwareError(
        "Perangkat ini tidak mendukung transkripsi audio (GPU tidak "
        "terdeteksi dan CPU tidak sanggup menjalankan mesin ASR). "
        "Aplikasi tidak bisa dijalankan di perangkat ini."
    )
