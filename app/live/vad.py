from dataclasses import dataclass

import numpy as np
import torch


@dataclass
class SpeechSegment:
    start_sample: int
    audio: bytes


def _bytes_to_tensor(window: bytes) -> "torch.Tensor":
    audio_int16 = np.frombuffer(window, dtype=np.int16)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0
    return torch.from_numpy(audio_float32)


class SpeechSegmenter:
    CHUNK_SAMPLES = 512  # silero-vad's required window size at 16kHz

    def __init__(self, vad_iterator, samplerate: int = 16000):
        self._vad_iterator = vad_iterator
        self._samplerate = samplerate
        self._pending = bytearray()
        self._speech_buffer = bytearray()
        self._in_speech = False
        self._samples_seen = 0
        self._speech_start_sample: int | None = None

    def process_chunk(self, chunk: bytes) -> list[SpeechSegment]:
        self._pending.extend(chunk)
        completed: list[SpeechSegment] = []
        window_bytes = self.CHUNK_SAMPLES * 2
        while len(self._pending) >= window_bytes:
            window = bytes(self._pending[:window_bytes])
            del self._pending[:window_bytes]
            completed.extend(self._process_window(window))
        return completed

    def _process_window(self, window: bytes) -> list[SpeechSegment]:
        window_start_sample = self._samples_seen
        self._samples_seen += self.CHUNK_SAMPLES

        tensor = _bytes_to_tensor(window)
        event = self._vad_iterator(tensor, return_seconds=False)

        completed: list[SpeechSegment] = []
        if event and "start" in event:
            self._in_speech = True
            self._speech_buffer = bytearray()
            self._speech_start_sample = window_start_sample
        if self._in_speech:
            self._speech_buffer.extend(window)
        if event and "end" in event:
            self._in_speech = False
            completed.append(SpeechSegment(
                start_sample=self._speech_start_sample,
                audio=bytes(self._speech_buffer),
            ))
            self._speech_buffer = bytearray()
            self._speech_start_sample = None
        return completed


def load_silero_vad_iterator(samplerate: int = 16000):
    from silero_vad import VADIterator, load_silero_vad

    model = load_silero_vad()
    return VADIterator(model, sampling_rate=samplerate)
