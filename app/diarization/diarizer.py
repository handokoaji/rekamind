import warnings
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

# pyannote.audio warns at import time if torchcodec's native libs don't match
# the installed FFmpeg/torch build. Harmless here: diarize() below always
# hands pyannote an in-memory waveform (via soundfile), never a path, so its
# torchcodec-based path-decoding is never actually used.
warnings.filterwarnings("ignore", message=r"\ntorchcodec is not installed correctly.*", category=UserWarning)
from pyannote.audio import Pipeline


@dataclass
class SpeakerSegment:
    start_ms: int
    end_ms: int
    label: str


# Below this, pyannote's embedding pooling layer gets a near-empty window
# (see the "std(): degrees of freedom <= 0" warning) -- observed to crash the
# whole process natively (access violation / heap corruption) on CUDA rather
# than raise a catchable Python exception. A live meeting's early diarize
# ticks can hit this before the speaker side has accumulated real audio.
MIN_DIARIZE_DURATION_SECONDS = 1.0


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
        wav_path = Path(wav_path)
        # A WavFileWriter creates its file on open but only writes the RIFF
        # header once the first frame arrives, so during a live meeting's
        # early ticks the file can be 0 bytes (or header-only, 44 bytes) --
        # not yet readable by soundfile. Nothing to diarize yet either way.
        if not wav_path.exists() or wav_path.stat().st_size <= 44:
            return []
        with wave.open(str(wav_path), "rb") as wf:
            duration_seconds = wf.getnframes() / wf.getframerate()
        if duration_seconds < MIN_DIARIZE_DURATION_SECONDS:
            return []
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
