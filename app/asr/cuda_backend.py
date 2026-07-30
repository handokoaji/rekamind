from pathlib import Path

from faster_whisper import WhisperModel

from app.asr.base import TranscriptSegmentResult


class FasterWhisperBackend:
    def __init__(self, model_size: str = "large-v3", device: str = "cuda", compute_type: str = "float32"):
        # float16 isn't "efficient" on Pascal-generation GPUs (e.g. GTX 1080 Ti,
        # one of the two mandated target machines) and ctranslate2 raises rather
        # than silently falling back; float32 works everywhere.
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        segments, _info = self._model.transcribe(str(wav_path), language=language)
        return [
            TranscriptSegmentResult(
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                text=seg.text.strip(),
            )
            for seg in segments
        ]
