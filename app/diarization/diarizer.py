from dataclasses import dataclass
from pathlib import Path

import torch
from pyannote.audio import Pipeline


@dataclass
class SpeakerSegment:
    start_ms: int
    end_ms: int
    label: str


class Diarizer:
    def __init__(self, hf_token: str, device: str = "cpu"):
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=hf_token
        )
        self._pipeline.to(torch.device(device))
        self._device = device

    def diarize(self, wav_path: Path) -> list[SpeakerSegment]:
        annotation = self._pipeline(str(wav_path))
        speaker_numbers: dict[str, int] = {}
        segments = []
        for turn, _, raw_label in annotation.itertracks(yield_label=True):
            if raw_label not in speaker_numbers:
                speaker_numbers[raw_label] = len(speaker_numbers) + 1
            segments.append(SpeakerSegment(
                start_ms=int(turn.start * 1000),
                end_ms=int(turn.end * 1000),
                label=f"Speaker {speaker_numbers[raw_label]}",
            ))
        return segments
