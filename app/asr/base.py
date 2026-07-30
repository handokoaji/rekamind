from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TranscriptSegmentResult:
    start_ms: int
    end_ms: int
    text: str


class TranscriberBackend(Protocol):
    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        ...
