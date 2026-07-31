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


def _load_waveform(wav_path: Path, start_frame: int = 0) -> dict:
    # Read via soundfile and hand pyannote an in-memory waveform instead of a
    # path: the pipeline's own path-decoding goes through torchcodec, whose
    # native libs must match both the installed FFmpeg AND torch build
    # exactly (this has broken twice across otherwise-unrelated env changes).
    # start_frame seeks on disk (soundfile), so windowing never reads the part
    # of the file we're about to discard.
    audio, samplerate = sf.read(str(wav_path), start=start_frame, dtype="float32")
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

    def diarize(self, wav_path: Path, window_seconds: float | None = None) -> list[SpeakerSegment]:
        """window_seconds, if given, only feeds pyannote the last N seconds of
        the file instead of the whole thing. Used by the live preview loop,
        which re-diarizes on every tick -- without a cap, a long meeting's
        diarize time grows with the recording and eventually blows past the
        live worker's timeout (see ProcessIsolatedDiarizer). The one-shot
        batch pass after a meeting ends always calls this with no window."""
        wav_path = Path(wav_path)
        # A WavFileWriter creates its file on open but only writes the RIFF
        # header once the first frame arrives, so during a live meeting's
        # early ticks the file can be 0 bytes (or header-only, 44 bytes) --
        # not yet readable by soundfile. Nothing to diarize yet either way.
        if not wav_path.exists() or wav_path.stat().st_size <= 44:
            return []
        with wave.open(str(wav_path), "rb") as wf:
            total_frames = wf.getnframes()
            samplerate = wf.getframerate()
        duration_seconds = total_frames / samplerate
        if duration_seconds < MIN_DIARIZE_DURATION_SECONDS:
            return []
        window_start_seconds = 0.0
        start_frame = 0
        if window_seconds is not None and duration_seconds > window_seconds:
            window_start_seconds = duration_seconds - window_seconds
            start_frame = int(window_start_seconds * samplerate)
        output = self._pipeline(_load_waveform(wav_path, start_frame))
        # pyannote.audio >= 4 returns a DiarizeOutput wrapping several
        # Annotations; older/legacy pipelines return the Annotation directly.
        annotation = getattr(output, "exclusive_speaker_diarization", output)

        speaker_numbers: dict[str, int] = {}
        segments = []
        for turn, _, raw_label in annotation.itertracks(yield_label=True):
            if raw_label not in speaker_numbers:
                speaker_numbers[raw_label] = len(speaker_numbers) + 1
            segments.append(SpeakerSegment(
                start_ms=int((turn.start + window_start_seconds) * 1000),
                end_ms=int((turn.end + window_start_seconds) * 1000),
                label=f"Speaker {speaker_numbers[raw_label]}",
            ))
        return segments
