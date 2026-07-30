from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.asr.base import TranscriberBackend
from app.audio.wav_writer import WavFileWriter
from app.live.vad import SpeechSegmenter


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
    ):
        self._source = source
        self._segmenter = segmenter
        self._transcriber = transcriber
        self._scratch_dir = scratch_dir
        self._samplerate = samplerate
        self._on_segment = on_segment
        self._segment_counter = 0

    def feed_chunk(self, chunk: bytes) -> None:
        for segment in self._segmenter.process_chunk(chunk):
            self._transcribe_segment(segment)

    def _transcribe_segment(self, segment) -> None:
        self._segment_counter += 1
        temp_path = self._scratch_dir / f"{self._source}_{self._segment_counter}.wav"
        with WavFileWriter(temp_path, self._samplerate, channels=1) as writer:
            writer.write_frames(segment.audio)

        offset_ms = int(segment.start_sample / self._samplerate * 1000)
        for result in self._transcriber.transcribe(temp_path, language="id"):
            self._on_segment(LiveSegment(
                source=self._source,
                start_ms=offset_ms + result.start_ms,
                end_ms=offset_ms + result.end_ms,
                text=result.text,
            ))
