from pathlib import Path

from app.asr.base import TranscriptSegmentResult
from app.live.pipeline import LiveSegment, StreamLivePipeline
from app.live.vad import SpeechSegment


class FakeSegmenter:
    def __init__(self, segments_per_call):
        self._segments_per_call = list(segments_per_call)

    def process_chunk(self, chunk):
        return self._segments_per_call.pop(0) if self._segments_per_call else []


class FakeTranscriber:
    def __init__(self, results):
        self._results = results
        self.transcribed_paths = []

    def transcribe(self, wav_path, language="id"):
        self.transcribed_paths.append(wav_path)
        return self._results


def test_feed_chunk_transcribes_completed_segments_with_absolute_timestamps(tmp_path):
    silence_window = (0).to_bytes(2, "little", signed=True) * 512
    segmenter = FakeSegmenter([
        [SpeechSegment(start_sample=16000, audio=silence_window)],  # 1.0s in at 16kHz
    ])
    transcriber = FakeTranscriber([
        TranscriptSegmentResult(start_ms=0, end_ms=500, text="halo"),
    ])
    received: list[LiveSegment] = []

    pipeline = StreamLivePipeline(
        source="mic", segmenter=segmenter, transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=received.append,
    )

    pipeline.feed_chunk(silence_window)

    assert len(transcriber.transcribed_paths) == 1
    assert transcriber.transcribed_paths[0].exists()
    assert received == [LiveSegment(source="mic", start_ms=1000, end_ms=1500, text="halo")]


def test_feed_chunk_does_nothing_when_no_segment_completes(tmp_path):
    segmenter = FakeSegmenter([[]])
    transcriber = FakeTranscriber([])
    received = []

    pipeline = StreamLivePipeline(
        source="speaker", segmenter=segmenter, transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=received.append,
    )
    pipeline.feed_chunk(b"\x00\x00" * 512)

    assert received == []
    assert transcriber.transcribed_paths == []
