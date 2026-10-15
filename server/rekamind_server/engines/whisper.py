import logging
import threading
from pathlib import Path

from .base import AsrSegment

log = logging.getLogger(__name__)

# Whisper invents boilerplate ("Terima kasih telah menonton") on silence/noise.
# faster-whisper scores this per segment; anything it already suspects is silence
# is dropped. Same threshold as faster-whisper's own default, carried over from v1.
NO_SPEECH_PROB_THRESHOLD = 0.6


def choose_compute(device: str, supported: set[str]) -> str:
    """float16 where the GPU runs it well; otherwise int8 (a Pascal card such as the GTX 10xx has no
    fast float16, and float32 on large-v3 takes ~9.5 GB of an 11 GB card for a slower result than
    int8 at ~4 GB; measured on a GTX 1080 Ti). CPU always int8."""
    if device != "cuda":
        return "int8"
    for c in ("float16", "int8_float16", "int8", "int8_float32"):
        if c in supported:
            return c
    return "float32"


def pick_device_and_compute(device: str, compute_type: str) -> tuple[str, str]:
    """auto -> cuda when ctranslate2 sees a GPU (not torch: torch may be a CPU wheel)."""
    import ctranslate2

    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    if compute_type == "auto":
        compute_type = choose_compute(device, set(ctranslate2.get_supported_compute_types(device)))
    return device, compute_type


def _is_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower()


class FasterWhisperTranscriber:
    """Lazy and releasable: nothing is loaded until the first job, and release()
    gives the VRAM back when the queue is empty."""

    def __init__(self, model: str = "large-v3", device: str = "auto", compute_type: str = "auto", glossary: str = ""):
        self._model_name, self._device, self._compute = model, device, compute_type
        self._glossary = glossary
        self._model = None
        self._fallback: list[tuple[str, str]] = []  # (device, compute) to try next if the GPU runs out of memory
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                device, compute = self._fallback.pop(0) if self._fallback else pick_device_and_compute(self._device, self._compute)
                self._current = (device, compute)
                log.info("loading whisper %s on %s (%s)", self._model_name, device, compute)
                self._model = WhisperModel(self._model_name, device=device, compute_type=compute)
            return self._model

    def _degrade_after_oom(self) -> bool:
        """The GPU ran out of memory: drop the model and retry lighter (int8 on the GPU, then the CPU)."""
        device, compute = getattr(self, "_current", ("cpu", "int8"))
        ladder = []
        if device == "cuda" and compute != "int8":
            ladder.append(("cuda", "int8"))
        if device == "cuda":
            ladder.append(("cpu", "int8"))
        if not ladder:
            return False
        log.warning("whisper out of memory on %s/%s; retrying as %s", device, compute, ladder[0])
        self._fallback = ladder
        self.release()
        return True

    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        try:
            return self._transcribe(wav, language)
        except RuntimeError as exc:
            if not _is_oom(exc) or not self._degrade_after_oom():
                raise
            return self.transcribe(wav, language)

    def _transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        prompt = ", ".join(t.strip() for t in self._glossary.replace("\n", ",").split(",") if t.strip()) or None
        segments, _ = self._load().transcribe(
            str(wav),
            language=language,
            vad_filter=True,  # skip long silences: faster, and fewer hallucinations
            condition_on_previous_text=False,  # one bad segment must not poison the rest
            initial_prompt=prompt,
            word_timestamps=True,  # so a sentence that spans two speakers can be cut where the voice changes
        )
        return [
            AsrSegment(int(s.start * 1000), int(s.end * 1000), s.text.strip(),
                       tuple((int(w.start * 1000), int(w.end * 1000), w.word) for w in (getattr(s, "words", None) or ())))
            for s in segments
            if s.no_speech_prob < NO_SPEECH_PROB_THRESHOLD and s.text.strip()
        ]

    def release(self) -> None:
        with self._lock:
            self._model = None
        import gc

        gc.collect()
