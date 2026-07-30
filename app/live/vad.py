import functools
from dataclasses import dataclass

import numpy as np


@dataclass
class SpeechSegment:
    start_sample: int
    audio: bytes


def _bytes_to_tensor(window: bytes) -> "torch.Tensor":
    import torch
    audio_int16 = np.frombuffer(window, dtype=np.int16)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0
    return torch.from_numpy(audio_float32)


class SpeechSegmenter:
    CHUNK_SAMPLES = 512  # silero-vad's required window size at 16kHz
    MAX_SEGMENT_SECONDS = 20  # force-close a segment that never gets a VAD end event

    def __init__(self, vad_iterator, samplerate: int = 16000):
        self._vad_iterator = vad_iterator
        self._samplerate = samplerate
        self._pending = bytearray()
        self._pending_start_sample = 0
        self._speech_buffer = bytearray()
        self._in_speech = False
        # Position in the VAD iterator's own sample space (it counts only what it
        # was fed). Kept separate from the absolute capture position below so a
        # dropped chunk shifts one and not the other.
        self._samples_seen = 0
        self._speech_start_sample: int | None = None

    def process_chunk(self, chunk: bytes, absolute_start_sample: int) -> list[SpeechSegment]:
        """`absolute_start_sample` is the number of samples the capture device
        produced before this chunk -- including any chunk that was dropped on a
        full live queue. Self-counting here would drift permanently on a drop,
        and the timestamps are matched against a diarization of the complete WAV.
        """
        expected = self._pending_start_sample + len(self._pending) // 2
        if not self._pending or absolute_start_sample != expected:
            # A gap (dropped chunk): the leftover no longer joins this chunk.
            self._pending = bytearray()
            self._pending_start_sample = absolute_start_sample
        self._pending.extend(chunk)

        completed: list[SpeechSegment] = []
        window_bytes = self.CHUNK_SAMPLES * 2
        while len(self._pending) >= window_bytes:
            window = bytes(self._pending[:window_bytes])
            del self._pending[:window_bytes]
            window_start_sample = self._pending_start_sample
            self._pending_start_sample += self.CHUNK_SAMPLES
            completed.extend(self._process_window(window, window_start_sample))
        return completed

    def _process_window(self, window: bytes, window_start_sample: int) -> list[SpeechSegment]:
        vad_window_start = self._samples_seen
        self._samples_seen += self.CHUNK_SAMPLES

        tensor = _bytes_to_tensor(window)
        event = self._vad_iterator(tensor, return_seconds=False)

        completed: list[SpeechSegment] = []
        if event and "start" in event:
            self._in_speech = True
            self._speech_buffer = bytearray()
            # VADIterator reports positions in its own sample space; translate the
            # offset it applies (speech padding) onto the absolute capture position.
            self._speech_start_sample = window_start_sample + (event["start"] - vad_window_start)
        if self._in_speech:
            max_bytes = self.MAX_SEGMENT_SECONDS * self._samplerate * 2
            if len(self._speech_buffer) + len(window) > max_bytes:
                # Continuous (or stuck-triggered) speech: emit what we have and
                # start a fresh segment at this window rather than buffering
                # forever waiting for an end event that may never come.
                completed.append(SpeechSegment(
                    start_sample=self._speech_start_sample,
                    audio=bytes(self._speech_buffer),
                ))
                self._speech_buffer = bytearray()
                self._speech_start_sample = window_start_sample
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


@functools.lru_cache(maxsize=1)
def _load_silero_model():
    # The model load is the expensive part (~seconds) and is stateless; the
    # iterator wrapped around it is not, so only this half is cached.
    from silero_vad import load_silero_vad
    return load_silero_vad()


def load_silero_vad_iterator(samplerate: int = 16000):
    from silero_vad import VADIterator

    # Always a FRESH iterator: it carries per-session trigger state that must not
    # leak from one meeting into the next.
    return VADIterator(_load_silero_model(), sampling_rate=samplerate)
