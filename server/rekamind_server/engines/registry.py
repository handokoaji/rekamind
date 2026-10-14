from ..config import Settings
from .base import Engines


def build_engines(settings: Settings) -> Engines | None:
    """Wire concrete engines from settings. Heavy imports stay inside the branches so
    a server running only the API/queue never pays for torch or ctranslate2."""
    name = settings.engines
    if name == "none":
        return None
    if name == "fake":
        from .fake import fake_engines

        return fake_engines()
    if name != "local":
        raise ValueError(f"REKAMIND_ENGINES='{name}' tidak dikenal (none | fake | local)")

    from .llm import OpenAiCompatExtractor
    from .whisper import FasterWhisperTranscriber

    transcriber = FasterWhisperTranscriber(settings.whisper_model, settings.whisper_device,
                                           settings.whisper_compute_type, settings.glossary)
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
        "transcriber": f"faster-whisper {settings.whisper_model} ({settings.whisper_device})",
        "diarizer": settings.diarizer,
        "extractor": f"{settings.llm_model} @ {settings.llm_base_url}",
    }, release=release)
