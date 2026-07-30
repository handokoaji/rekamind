import wave

from app.asr.base import TranscriptSegmentResult
from app.live.pipeline import LiveSegment, StreamLivePipeline
from app.live.vad import SpeechSegment


class FakeSegmenter:
    def __init__(self, segments_per_call):
        self._segments_per_call = list(segments_per_call)
        self.received_chunks = []

    def process_chunk(self, chunk, absolute_start_sample):
        self.received_chunks.append((chunk, absolute_start_sample))
        return self._segments_per_call.pop(0) if self._segments_per_call else []


class FakeTranscriber:
    def __init__(self, results):
        self._results = results
        self.transcribed_paths = []
        self.frames_seen = []

    def transcribe(self, wav_path, language="id"):
        self.transcribed_paths.append(wav_path)
        with wave.open(str(wav_path), "rb") as wf:
            self.frames_seen.append((wf.getnframes(), wf.getframerate(), wf.getnchannels()))
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

    pipeline.feed_chunk(silence_window, 0)

    assert len(transcriber.transcribed_paths) == 1
    assert received == [LiveSegment(source="mic", start_ms=1000, end_ms=1500, text="halo")]


def test_feed_chunk_does_nothing_when_no_segment_completes(tmp_path):
    segmenter = FakeSegmenter([[]])
    transcriber = FakeTranscriber([])
    received = []

    pipeline = StreamLivePipeline(
        source="speaker", segmenter=segmenter, transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=received.append,
    )
    pipeline.feed_chunk(b"\x00\x00" * 512, 0)

    assert received == []
    assert transcriber.transcribed_paths == []


def test_scratch_wav_is_deleted_after_transcription(tmp_path):
    """I9: one scratch file per speech segment would otherwise pile up all meeting."""
    window = (0).to_bytes(2, "little", signed=True) * 512
    segmenter = FakeSegmenter([[SpeechSegment(start_sample=0, audio=window)]])
    transcriber = FakeTranscriber([TranscriptSegmentResult(start_ms=0, end_ms=1, text="x")])

    pipeline = StreamLivePipeline(
        source="mic", segmenter=segmenter, transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=lambda s: None,
    )
    pipeline.feed_chunk(window, 0)

    assert transcriber.transcribed_paths[0].exists() is False
    assert list(tmp_path.glob("*.wav")) == []


def test_scratch_wav_is_deleted_even_when_transcription_fails(tmp_path):
    window = (0).to_bytes(2, "little", signed=True) * 512
    segmenter = FakeSegmenter([[SpeechSegment(start_sample=0, audio=window)]])

    class BoomTranscriber:
        def transcribe(self, wav_path, language="id"):
            raise RuntimeError("boom")

    pipeline = StreamLivePipeline(
        source="mic", segmenter=segmenter, transcriber=BoomTranscriber(),
        scratch_dir=tmp_path, samplerate=16000, on_segment=lambda s: None,
    )
    try:
        pipeline.feed_chunk(window, 0)
    except RuntimeError:
        pass

    assert list(tmp_path.glob("*.wav")) == []


def _interleaved_stereo_48k(frames: int) -> bytes:
    """Two distinguishable channels of non-trivial int16 at 48kHz."""
    import numpy as np

    t = np.arange(frames, dtype=np.float32)
    left = (8000 * np.sin(2 * np.pi * 220 * t / 48000)).astype(np.int16)
    right = (4000 * np.sin(2 * np.pi * 440 * t / 48000)).astype(np.int16)
    return np.stack([left, right], axis=1).astype(np.int16).tobytes()


def test_native_48k_stereo_source_is_downmixed_and_resampled_to_16k_mono(tmp_path):
    """C1: WASAPI loopback delivers the device's native format. Fed straight to a
    16kHz-mono VAD it is garbage; the pipeline must convert at its entry point."""
    frames = 48000  # exactly 1 second at 48kHz
    chunk = _interleaved_stereo_48k(frames)
    assert len(chunk) == frames * 2 * 2  # 2 channels x 2 bytes

    captured = {}

    class CapturingSegmenter:
        def process_chunk(self, converted_chunk, absolute_start_sample):
            captured["chunk"] = converted_chunk
            captured["abs"] = absolute_start_sample
            return [SpeechSegment(start_sample=absolute_start_sample, audio=converted_chunk)]

    transcriber = FakeTranscriber([TranscriptSegmentResult(start_ms=0, end_ms=1000, text="halo")])
    received: list[LiveSegment] = []

    pipeline = StreamLivePipeline(
        source="speaker", segmenter=CapturingSegmenter(), transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=received.append,
        source_samplerate=48000, source_channels=2,
    )

    pipeline.feed_chunk(chunk, 96000)  # 2 seconds of native 48kHz frames already captured

    # Mono int16 at 16kHz: one third of the input's per-channel frame count.
    converted_samples = len(captured["chunk"]) // 2
    assert abs(converted_samples - frames // 3) <= 2
    # The absolute tag is rescaled into 16kHz sample space too (2s -> 32000).
    assert captured["abs"] == 32000

    # The scratch WAV the transcriber actually received is 16kHz mono ~1s.
    nframes, framerate, nchannels = transcriber.frames_seen[0]
    assert (framerate, nchannels) == (16000, 1)
    assert abs(nframes - 16000) <= 2
    # ...and its timestamps are anchored at 2s, not at 6s (the un-rescaled tag).
    assert received[0].start_ms == 2000


def test_16k_mono_source_is_passed_through_untouched(tmp_path):
    window = (1234).to_bytes(2, "little", signed=True) * 512
    segmenter = FakeSegmenter([[]])

    pipeline = StreamLivePipeline(
        source="mic", segmenter=segmenter, transcriber=FakeTranscriber([]),
        scratch_dir=tmp_path, samplerate=16000, on_segment=lambda s: None,
    )
    pipeline.feed_chunk(window, 512)

    assert segmenter.received_chunks == [(window, 512)]
