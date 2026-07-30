import queue
import time

from app.live.session import LiveSession


class FakeSegmenter:
    """Treats every chunk as one completed speech segment (skips real VAD windowing)."""
    def process_chunk(self, chunk, absolute_start_sample):
        from app.live.vad import SpeechSegment
        return [SpeechSegment(start_sample=absolute_start_sample, audio=chunk)]


class FakeTranscriber:
    def __init__(self, text):
        self._text = text

    def transcribe(self, wav_path, language="id"):
        from app.asr.base import TranscriptSegmentResult
        return [TranscriptSegmentResult(start_ms=0, end_ms=500, text=self._text)]


class FakeDiarizer:
    def diarize(self, wav_path):
        return []


def _chunk(samples: int = 512) -> tuple[bytes, int]:
    return (b"\x00\x00" * samples, 0)


def test_start_feeds_queued_chunks_through_pipeline_and_reports_text_events(tmp_path):
    mic_queue = queue.Queue()
    speaker_queue = queue.Queue()
    events = []

    session = LiveSession(
        mic_transcriber=FakeTranscriber("Selamat pagi"),
        speaker_transcriber=FakeTranscriber("Mari mulai"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=mic_queue,
        speaker_queue=speaker_queue,
        diarize_interval_seconds=999,  # long enough it won't fire during this test
        on_update=events.append,
    )

    session.start()
    mic_queue.put(_chunk())
    speaker_queue.put(_chunk())

    deadline = time.time() + 5
    while len(events) < 2 and time.time() < deadline:
        time.sleep(0.05)

    session.stop()

    texts = {e["segment"].text for e in events if e["type"] == "text"}
    assert texts == {"Selamat pagi", "Mari mulai"}

    mic_segments, speaker_segments = session.get_segments()
    assert [s.text for s in mic_segments] == ["Selamat pagi"]
    assert [s.text for s in speaker_segments] == ["Mari mulai"]


def test_stop_unblocks_consumer_threads_promptly(tmp_path):
    session = LiveSession(
        mic_transcriber=FakeTranscriber("x"),
        speaker_transcriber=FakeTranscriber("y"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=queue.Queue(),
        speaker_queue=queue.Queue(),
        diarize_interval_seconds=999,
        on_update=lambda e: None,
    )
    session.start()
    start = time.time()
    session.stop()
    assert time.time() - start < 3  # stop() must not hang waiting on empty queues


def test_stop_does_not_block_on_a_full_bounded_queue_or_drain_its_backlog(tmp_path):
    """I3: production queues are bounded (maxsize=200). A sentinel-based stop
    would block on put() and then wait behind the whole backlog."""
    mic_queue = queue.Queue(maxsize=3)
    speaker_queue = queue.Queue(maxsize=3)

    class SlowTranscriber:
        def transcribe(self, wav_path, language="id"):
            from app.asr.base import TranscriptSegmentResult
            time.sleep(0.4)
            return [TranscriptSegmentResult(start_ms=0, end_ms=1, text="lambat")]

    session = LiveSession(
        mic_transcriber=SlowTranscriber(),
        speaker_transcriber=SlowTranscriber(),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=mic_queue,
        speaker_queue=speaker_queue,
        diarize_interval_seconds=999,
        on_update=lambda e: None,
    )
    for _ in range(3):
        mic_queue.put_nowait(_chunk())
        speaker_queue.put_nowait(_chunk())
    assert mic_queue.full()

    session.start()
    start = time.time()
    session.stop()
    # Draining 3 x 0.4s of backlog per source would take >1.2s; abandoning it is fast.
    assert time.time() - start < 2


class BrokenThenWorkingTranscriber:
    """Raises once (simulating a transient live-pipeline error), then works normally."""
    def __init__(self):
        self._call_count = 0

    def transcribe(self, wav_path, language="id"):
        from app.asr.base import TranscriptSegmentResult
        self._call_count += 1
        if self._call_count == 1:
            raise RuntimeError("simulated transient ASR failure")
        return [TranscriptSegmentResult(start_ms=0, end_ms=500, text="pulih setelah error")]


def test_feed_chunk_error_is_logged_and_does_not_kill_consumer_thread(tmp_path):
    mic_queue = queue.Queue()
    events = []

    session = LiveSession(
        mic_transcriber=BrokenThenWorkingTranscriber(),
        speaker_transcriber=FakeTranscriber("y"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=mic_queue,
        speaker_queue=queue.Queue(),
        diarize_interval_seconds=999,
        on_update=events.append,
    )

    session.start()
    mic_queue.put(_chunk())  # first chunk: transcriber raises, must not kill the thread
    mic_queue.put(_chunk())  # second chunk: thread must still be alive to process this

    deadline = time.time() + 5
    while not events and time.time() < deadline:
        time.sleep(0.05)

    session.stop()

    assert len(events) == 1
    assert events[0]["segment"].text == "pulih setelah error"


def test_speaker_pipeline_is_built_with_the_native_device_format(tmp_path):
    """C1: only the speaker source needs conversion; mic capture is already 16k mono."""
    session = LiveSession(
        mic_transcriber=FakeTranscriber("x"),
        speaker_transcriber=FakeTranscriber("y"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=queue.Queue(),
        speaker_queue=queue.Queue(),
        diarize_interval_seconds=999,
        on_update=lambda e: None,
        speaker_samplerate=48000,
        speaker_channels=2,
    )
    assert session._speaker_pipeline._source_samplerate == 48000
    assert session._speaker_pipeline._source_channels == 2
    assert session._mic_pipeline._source_samplerate == 16000
    assert session._mic_pipeline._source_channels == 1
