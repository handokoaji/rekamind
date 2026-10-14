import logging
import threading
from pathlib import Path

from .base import AsrSegment

log = logging.getLogger(__name__)

# Whisper invents boilerplate ("Terima kasih telah menonton") on silence/noise.
# faster-whisper scores this per segment; anything it already suspects is silence
# is dropped. Same threshold as faster-whisper's own default, carried over from v1.
NO_SPEECH_PROB_THRESHOLD = 0.6


def pick_device_and_compute(device: str, compute_type: str) -> tuple[str, str]:
    """auto -> cuda when ctranslate2 sees a GPU (not torch: torch may be a CPU wheel),
    float16 only if the GPU reports it as efficient. Pascal cards (e.g. GTX 10xx) do not,
    and ctranslate2 raises instead of silently falling back, so they get float32."""
    import ctranslate2

    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    if compute_type == "auto":
        if device == "cuda":
            compute_type = "float16" if "float16" in ctranslate2.get_supported_compute_types("cuda") else "float32"
        else:
            compute_type = "int8"
    return device, compute_type


class FasterWhisperTranscriber:
    """Lazy and releasable: nothing is loaded until the first job, and release()
    gives the VRAM back when the queue is empty."""

    def __init__(self, model: str = "large-v3", device: str = "auto", compute_type: str = "auto", glossary: str = ""):
        self._model_name, self._device, self._compute = model, device, compute_type
        self._glossary = glossary
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                device, compute = pick_device_and_compute(self._device, self._compute)
                log.info("loading whisper %s on %s (%s)", self._model_name, device, compute)
                self._model = WhisperModel(self._model_name, device=device, compute_type=compute)
            return self._model

    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        prompt = ", ".join(t.strip() for t in self._glossary.replace("\n", ",").split(",") if t.strip()) or None
        segments, _ = self._load().transcribe(
            str(wav),
            language=language,
            vad_filter=True,  # skip long silences: faster, and fewer hallucinations
            condition_on_previous_text=False,  # one bad segment must not poison the rest
            initial_prompt=prompt,
        )
        return [
            AsrSegment(int(s.start * 1000), int(s.end * 1000), s.text.strip())
            for s in segments
            if s.no_speech_prob < NO_SPEECH_PROB_THRESHOLD and s.text.strip()
        ]

    def release(self) -> None:
        with self._lock:
            self._model = None
        import gc

        gc.collect()
