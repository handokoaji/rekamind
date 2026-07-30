import asyncio
import queue
import time

from sqlalchemy import select

from app.live.pipeline import LiveSegment
from app.live.session import LiveSession
from app.pipeline.merge import MergedSegment
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.models import Speaker, TranscriptSegment


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


def _make_db():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    return make_session_factory(engine)


def _drafts(session_factory) -> list[TranscriptSegment]:
    async def _read():
        async with session_factory() as session:
            result = await session.execute(
                select(TranscriptSegment).order_by(TranscriptSegment.id)
            )
            return list(result.scalars().all())
    return asyncio.run(_read())


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


def test_live_text_is_saved_as_a_draft_segment(tmp_path):
    """I6: a crash before "Stop" must still leave a partial transcript behind."""
    session_factory = _make_db()

    async def _create_meeting():
        from app.storage import repository as repo
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Draft", None)
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_create_meeting())

    mic_queue = queue.Queue()
    events = []
    session = LiveSession(
        mic_transcriber=FakeTranscriber("halo semua"),
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
        meeting_id=meeting_id,
        session_factory=session_factory,
    )

    session.start()
    mic_queue.put(_chunk())
    deadline = time.time() + 5
    while not events and time.time() < deadline:
        time.sleep(0.05)
    session.stop()

    rows = _drafts(session_factory)
    assert len(rows) == 1
    assert rows[0].text == "halo semua"
    assert rows[0].source == "mic"
    assert rows[0].is_final is False
    assert rows[0].speaker_id is None
    assert rows[0].meeting_id == meeting_id


def test_relabel_clears_old_drafts_and_resaves_with_resolved_speaker_ids(tmp_path):
    session_factory = _make_db()

    async def _seed():
        from app.storage import repository as repo
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Relabel", None)
            await repo.save_transcript_segments(session, [{
                "meeting_id": meeting.id, "speaker_id": None, "source": "speaker",
                "start_ms": 0, "end_ms": 100, "text": "draft lama", "is_final": False,
            }])
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())

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
        meeting_id=meeting_id,
        session_factory=session_factory,
    )

    session._save_relabeled_drafts([
        MergedSegment(source="mic", speaker_label="Anda", start_ms=0, end_ms=400, text="Selamat pagi"),
        MergedSegment(source="speaker", speaker_label="Speaker 1", start_ms=500, end_ms=900, text="Mari mulai"),
        MergedSegment(source="speaker", speaker_label="Speaker 1", start_ms=900, end_ms=1200, text="lagi"),
    ])

    rows = _drafts(session_factory)
    assert [r.text for r in rows] == ["Selamat pagi", "Mari mulai", "lagi"]  # "draft lama" cleared
    assert all(r.is_final is False for r in rows)
    assert rows[0].speaker_id is None  # "Anda" (mic) stays NULL

    async def _speakers():
        async with session_factory() as session:
            result = await session.execute(select(Speaker))
            return list(result.scalars().all())

    speakers = asyncio.run(_speakers())
    assert [s.label for s in speakers] == ["Speaker 1"]  # created once, reused
    assert rows[1].speaker_id == speakers[0].id
    assert rows[2].speaker_id == speakers[0].id


def test_draft_write_failure_is_logged_and_does_not_propagate(tmp_path, capsys):
    class BoomFactory:
        def __call__(self):
            raise RuntimeError("db is down")

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
        meeting_id=1,
        session_factory=BoomFactory(),
    )

    session._save_draft(LiveSegment(source="mic", start_ms=0, end_ms=1, text="x"))
    session._save_relabeled_drafts([])

    out = capsys.readouterr().out
    assert "db is down" in out


def test_no_session_factory_means_no_draft_writes(tmp_path):
    """Existing callers that pass no DB (and the tests above) must keep working."""
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
    session._save_draft(LiveSegment(source="mic", start_ms=0, end_ms=1, text="x"))  # no raise
