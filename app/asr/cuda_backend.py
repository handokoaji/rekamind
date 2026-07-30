from pathlib import Path

from faster_whisper import WhisperModel

from app.asr.base import TranscriptSegmentResult


class FasterWhisperBackend:
    def __init__(self, model_size: str = "large-v3", device: str = "cuda", compute_type: str = "float16"):
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
