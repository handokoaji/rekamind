from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from app.asr.base import TranscriberBackend
from app.audio.wav_writer import WavFileWriter
from app.live.vad import SpeechSegmenter

TARGET_SAMPLERATE = 16000  # silero-vad + whisper both want 16kHz mono


@dataclass
class LiveSegment:
    source: str
    start_ms: int
    end_ms: int
    text: str


class StreamLivePipeline:
    def __init__(
        self,
        source: str,
        segmenter: SpeechSegmenter,
        transcriber: TranscriberBackend,
        scratch_dir: Path,
        samplerate: int,
        on_segment: Callable[[LiveSegment], None],
        source_samplerate: int = TARGET_SAMPLERATE,
        source_channels: int = 1,
    ):
        self._source = source
        self._segmenter = segmenter
        self._transcriber = transcriber
        self._scratch_dir = scratch_dir
        self._samplerate = samplerate
        self._on_segment = on_segment
        self._source_samplerate = source_samplerate
        self._source_channels = source_channels
        self._segment_counter = 0

    def _to_target_format(self, chunk: bytes, want_samples: int) -> bytes:
        """Downmix + resample native capture audio to 16kHz mono int16.

        WASAPI loopback hands us the device's native format (typically 48kHz
        stereo). Same conversion as app/asr/openvino_backend.py's
        _load_audio_array, just on raw int16 bytes instead of a WAV file.

        ponytail: each chunk is resampled independently (no filter state carried
        across chunks), so there is a tiny artifact at every chunk boundary --
        inaudible to the small preview model. Carry resampler state across calls
        if the live text ever looks damaged at boundaries.
        """
        import torch
        import torchaudio

        audio = np.frombuffer(chunk, dtype=np.int16).reshape(-1, self._source_channels)
        audio = audio.astype(np.float32).mean(axis=1)
        if self._source_samplerate != TARGET_SAMPLERATE:
            audio = torchaudio.functional.resample(
                torch.from_numpy(audio), self._source_samplerate, TARGET_SAMPLERATE
            ).numpy()
        # torchaudio rounds the output length UP, while the absolute sample tags
        # below advance by the floor. Left alone, a contiguous capture would look
        # like it had a gap at every chunk and the segmenter would keep throwing
        # its partial window away. One sample at 16kHz is 0.06ms - just align it.
        audio = audio[:want_samples]
        out = np.clip(audio, -32768, 32767).astype(np.int16).tobytes()
        return out + b"\x00\x00" * (want_samples - len(audio))

    def feed_chunk(self, chunk: bytes, absolute_start_sample: int) -> None:
        if self._source_samplerate != TARGET_SAMPLERATE or self._source_channels != 1:
            # The tag is counted in native device frames; everything downstream of
            # here lives in 16kHz-mono sample space, so rescale it and make the
            # converted chunk exactly as long as that rescaling implies.
            frames = len(chunk) // (2 * self._source_channels)
            start = absolute_start_sample * TARGET_SAMPLERATE // self._source_samplerate
            end = (absolute_start_sample + frames) * TARGET_SAMPLERATE // self._source_samplerate
            chunk = self._to_target_format(chunk, end - start)
            absolute_start_sample = start
        for segment in self._segmenter.process_chunk(chunk, absolute_start_sample):
            self._transcribe_segment(segment)

    def _transcribe_segment(self, segment) -> None:
        self._segment_counter += 1
        temp_path = self._scratch_dir / f"{self._source}_{self._segment_counter}.wav"
        with WavFileWriter(temp_path, self._samplerate, channels=1) as writer:
            writer.write_frames(segment.audio)

        offset_ms = int(segment.start_sample / self._samplerate * 1000)
        try:
            for result in self._transcriber.transcribe(temp_path, language="id"):
                self._on_segment(LiveSegment(
                    source=self._source,
                    start_ms=offset_ms + result.start_ms,
                    end_ms=offset_ms + result.end_ms,
                    text=result.text,
                ))
        finally:
            # One scratch WAV per speech segment adds up over a long meeting.
            temp_path.unlink(missing_ok=True)
