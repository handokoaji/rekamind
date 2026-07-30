from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from pyannote.audio import Pipeline


@dataclass
class SpeakerSegment:
    start_ms: int
    end_ms: int
    label: str


def _load_waveform(wav_path: Path) -> dict:
    # Read via soundfile and hand pyannote an in-memory waveform instead of a
    # path: the pipeline's own path-decoding goes through torchcodec, whose
    # native libs must match both the installed FFmpeg AND torch build
    # exactly (this has broken twice across otherwise-unrelated env changes).
    audio, samplerate = sf.read(str(wav_path), dtype="float32")
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]
    waveform = torch.from_numpy(audio.T)  # (channel, time)
    return {"waveform": waveform, "sample_rate": samplerate}


class Diarizer:
    def __init__(self, hf_token: str, device: str = "cpu"):
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=hf_token
        )
        self._pipeline.to(torch.device(device))
        self._device = device

    def diarize(self, wav_path: Path) -> list[SpeakerSegment]:
        output = self._pipeline(_load_waveform(wav_path))
        # pyannote.audio >= 4 returns a DiarizeOutput wrapping several
        # Annotations; older/legacy pipelines return the Annotation directly.
        annotation = getattr(output, "exclusive_speaker_diarization", output)

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
