import logging
import threading
import wave
from pathlib import Path

from .base import SpeakerTurn

log = logging.getLogger(__name__)

# pyannote's pooling layer is observed to crash the process natively (not raise)
# on near-empty input, so refuse to run on anything shorter. Learned in v1.
MIN_SECONDS = 1.0


class PyannoteDiarizer:
    def __init__(self, hf_token: str, device: str = "auto"):
        if not hf_token:
            raise ValueError("REKAMIND_HF_TOKEN diperlukan untuk diarisasi pyannote")
        self._token, self._device = hf_token, device
        self._pipeline = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._pipeline is None:
                import torch
                from pyannote.audio import Pipeline

                p = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=self._token)
                device = "cuda" if self._device == "auto" and torch.cuda.is_available() else (
                    "cpu" if self._device == "auto" else self._device)
                p.to(torch.device(device))
                self._pipeline = p
            return self._pipeline

    def diarize(self, wav: Path, num_speakers: int | None = None) -> list[SpeakerTurn]:
        import numpy as np
        import soundfile as sf
        import torch

        if not wav.exists() or wav.stat().st_size <= 44:
            return []
        with wave.open(str(wav), "rb") as wf:
            if wf.getnframes() / wf.getframerate() < MIN_SECONDS:
                return []
        # In-memory waveform: pyannote's own path decoding needs torchcodec whose native
        # libs must match FFmpeg+torch exactly, which broke twice in v1.
        audio, sr = sf.read(str(wav), dtype="float32")
        if audio.ndim == 1:
            audio = audio[:, np.newaxis]
        # Left to itself pyannote often merges similar voices; the user's count fixes that (3 people were heard as 2).
        hint = {"num_speakers": num_speakers} if num_speakers else {}
        output = self._load()({"waveform": torch.from_numpy(audio.T), "sample_rate": sr}, **hint)
        annotation = getattr(output, "exclusive_speaker_diarization", output)
        numbers: dict[str, int] = {}
        turns = []
        for turn, _, raw in annotation.itertracks(yield_label=True):
            n = numbers.setdefault(raw, len(numbers))
            turns.append(SpeakerTurn(int(turn.start * 1000), int(turn.end * 1000), f"SPEAKER_{n:02d}"))
        return turns

    def release(self) -> None:
        with self._lock:
            self._pipeline = None
        import gc

        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:  # torch absent or no CUDA: nothing to free
            log.debug("cuda cache not cleared", exc_info=True)


class SingleSpeakerDiarizer:
    """Used when diarization is off: the whole speaker channel is one voice."""

    def diarize(self, wav: Path, num_speakers: int | None = None) -> list[SpeakerTurn]:
        return [SpeakerTurn(0, 10**9, "SPEAKER_00")]
