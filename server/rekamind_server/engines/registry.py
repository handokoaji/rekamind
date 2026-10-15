from ..config import Settings
from .base import Engines


def use_openvino(settings: Settings) -> bool:
    """Explicitly ("intel"), or automatically when the installed engine pack is the OpenVINO one."""
    if settings.whisper_device == "intel":
        return True
    if settings.whisper_device != "auto":
        return False
    from .. import enginepack

    return enginepack.installed_kind() == "openvino"


def use_vulkan(settings: Settings) -> bool:
    """Explicitly ("vulkan"), or automatically when the installed engine pack is the Vulkan (whisper.cpp) one."""
    if settings.whisper_device == "vulkan":
        return True
    if settings.whisper_device != "auto":
        return False
    from .. import enginepack

    return enginepack.installed_kind() == "vulkan"


def build_engines(settings: Settings) -> Engines | None:
    """Wire concrete engines from settings. Heavy imports stay inside the branches so
    a server running only the API/queue never pays for torch or ctranslate2."""
    name = settings.engines
    if name == "none":
        return None
    if name == "fake":
        from .fake import fake_engines

        return fake_engines()
    if name == "demo":
        from .fake import demo_engines

        return demo_engines()
    if name != "local":
        raise ValueError(f"REKAMIND_ENGINES='{name}' tidak dikenal (none | fake | demo | local)")

    if settings.hf_token:
        # huggingface_hub reads this: without it the Whisper download is anonymous (slower, rate-limited)
        # even though the token was set for the diarizer.
        import os

        os.environ.setdefault("HF_TOKEN", settings.hf_token)

    from .llm import OpenAiCompatExtractor
    from .whisper import FasterWhisperTranscriber

    if use_vulkan(settings):
        from .. import enginepack
        from .whispercpp import WhisperCppTranscriber

        enginepack.activate()
        transcriber = WhisperCppTranscriber(enginepack.default_pack_dir(), settings.whisper_model,
                                            settings.whispercpp_quant, settings.vulkan_device)
        transcriber_label = f"whisper.cpp Vulkan {settings.whisper_model} ({settings.whispercpp_quant})"
    elif use_openvino(settings):
        from .openvino import OpenVinoTranscriber

        transcriber = OpenVinoTranscriber(settings.whisper_model, settings.openvino_device)
        transcriber_label = f"OpenVINO whisper {settings.whisper_model} ({settings.openvino_device})"
    else:
        transcriber = FasterWhisperTranscriber(settings.whisper_model, settings.whisper_device,
                                               settings.whisper_compute_type, settings.glossary)
        transcriber_label = f"faster-whisper {settings.whisper_model} ({settings.whisper_device})"
    if settings.diarizer == "pyannote":
        from .pyannote import PyannoteDiarizer

        diarizer = PyannoteDiarizer(settings.hf_token)
    elif settings.diarizer == "none":
        from .pyannote import SingleSpeakerDiarizer

        diarizer = SingleSpeakerDiarizer()
    else:
        raise ValueError(f"REKAMIND_DIARIZER='{settings.diarizer}' tidak dikenal (none | pyannote)")

    extractor = OpenAiCompatExtractor(settings.llm_base_url, settings.llm_api_key, settings.llm_model,
                                      chunk_chars=settings.llm_chunk_chars)

    def release() -> None:
        for e in (transcriber, diarizer):
            getattr(e, "release", lambda: None)()

    return Engines(transcriber, diarizer, extractor, {
        "transcriber": transcriber_label,
        "diarizer": settings.diarizer,
        "extractor": f"{settings.llm_model} @ {settings.llm_base_url}",
    }, release=release)
