import asyncio
from datetime import datetime

from sqlalchemy import select

from app.asr.base import TranscriptSegmentResult
from app.storage.models import Summary, TranscriptSegment
from app.diarization.diarizer import SpeakerSegment
from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.summarization.groq_client import MomResult
from app.pipeline.finalize import finalize_meeting


class FakeTranscriber:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, wav_path, language="id"):
        return self._segments


class FakeDiarizer:
    def __init__(self, labels):
        self._labels = labels

    def diarize(self, wav_path):
        return self._labels


class FakeSummarizer:
    model = "llama-3.3-70b-versatile"

    def summarize(self, meeting_title, transcript_text):
        assert "Anda" in transcript_text
        assert "Speaker 1" in transcript_text
        return MomResult(
            minute_by_minute=[{"time": "00:00", "point": "Mulai"}],
            decisions=["Lanjut"],
            action_items=[],
            detailed_notes="Catatan.",
        )


class FailingSummarizer:
    model = "llama-3.3-70b-versatile"

    def summarize(self, meeting_title, transcript_text):
        raise RuntimeError("Summarizer failed")


def test_finalize_meeting_marks_failed_when_transcription_raises(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await repo.mark_meeting_status(session, meeting.id, "processing")
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        class ExplodingTranscriber:
            def transcribe(self, wav_path, language="id"):
                raise RuntimeError("CUDA out of memory")

        exception_raised = None
        async with session_factory() as session:
            try:
                await finalize_meeting(
                    session=session,
                    meeting_id=meeting_id,
                    meeting_title="Rapat Uji",
                    meeting_date=datetime(2026, 7, 30, 9, 0),
                    mic_wav=mic_wav,
                    speaker_wav=speaker_wav,
                    transcriber=ExplodingTranscriber(),
                    diarizer=FakeDiarizer([]),
                    summarizer=FakeSummarizer(),
                    docx_output_path=tmp_path / "mom.docx",
                )
                await session.commit()
            except RuntimeError as e:
                exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            summaries = (await session.execute(select(Summary))).scalars().all()
        return exception_raised, meetings, summaries

    exception_raised, meetings, summaries = asyncio.run(scenario())
    assert exception_raised is not None
    assert "CUDA out of memory" in str(exception_raised)
    # not left stuck at "processing"
    assert meetings[0].status == "failed"
    # summarization never started, so no Summary row is written
    assert summaries == []


def test_finalize_meeting_marks_failed_when_diarizer_raises(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await repo.mark_meeting_status(session, meeting.id, "processing")
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        class ExplodingDiarizer:
            def diarize(self, wav_path):
                raise RuntimeError("HF model download failed")

        exception_raised = None
        async with session_factory() as session:
            try:
                await finalize_meeting(
                    session=session,
                    meeting_id=meeting_id,
                    meeting_title="Rapat Uji",
                    meeting_date=datetime(2026, 7, 30, 9, 0),
                    mic_wav=mic_wav,
                    speaker_wav=speaker_wav,
                    transcriber=FakeTranscriber([
                        TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")
                    ]),
                    diarizer=ExplodingDiarizer(),
                    summarizer=FakeSummarizer(),
                    docx_output_path=tmp_path / "mom.docx",
                )
                await session.commit()
            except RuntimeError as e:
                exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            segments = (await session.execute(select(TranscriptSegment))).scalars().all()
        return exception_raised, meetings, segments

    exception_raised, meetings, segments = asyncio.run(scenario())
    assert exception_raised is not None
    assert "HF model download failed" in str(exception_raised)
    assert meetings[0].status == "failed"
    assert segments == []


def test_finalize_meeting_saves_segments_and_summary(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()
        docx_path = tmp_path / "mom.docx"

        transcriber_calls = {"mic.wav": [
            TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")
        ], "speaker.wav": [
            TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")
        ]}

        class RoutingFakeTranscriber:
            def transcribe(self, wav_path, language="id"):
                return transcriber_calls[wav_path.name]

        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])
        summarizer = FakeSummarizer()

        async with session_factory() as session:
            summary = await finalize_meeting(
                session=session,
                meeting_id=meeting_id,
                meeting_title="Rapat Uji",
                meeting_date=datetime(2026, 7, 30, 9, 0),
                mic_wav=mic_wav,
                speaker_wav=speaker_wav,
                transcriber=RoutingFakeTranscriber(),
                diarizer=diarizer,
                summarizer=summarizer,
                docx_output_path=docx_path,
            )
            await session.commit()

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return summary, meetings

    summary, meetings = asyncio.run(scenario())
    assert summary.status == "ready"
    assert meetings[0].status == "completed"
    assert (tmp_path / "mom.docx").exists()


def test_finalize_meeting_marks_failed_on_exception(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()
        docx_path = tmp_path / "mom.docx"

        transcriber_calls = {"mic.wav": [
            TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")
        ], "speaker.wav": [
            TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")
        ]}

        class RoutingFakeTranscriber:
            def transcribe(self, wav_path, language="id"):
                return transcriber_calls[wav_path.name]

        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])
        failing_summarizer = FailingSummarizer()

        # Mirror the real caller (RecorderController._finalize): one session, and
        # the caller's own commit is never reached when finalize_meeting raises.
        exception_raised = None
        async with session_factory() as session:
            try:
                await finalize_meeting(
                    session=session,
                    meeting_id=meeting_id,
                    meeting_title="Rapat Uji",
                    meeting_date=datetime(2026, 7, 30, 9, 0),
                    mic_wav=mic_wav,
                    speaker_wav=speaker_wav,
                    transcriber=RoutingFakeTranscriber(),
                    diarizer=diarizer,
                    summarizer=failing_summarizer,
                    docx_output_path=docx_path,
                )
                await session.commit()
            except RuntimeError as e:
                exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            segments = (await session.execute(select(TranscriptSegment))).scalars().all()
            summaries = (await session.execute(select(Summary))).scalars().all()
        return exception_raised, meetings, segments, summaries

    exception_raised, meetings, segments, summaries = asyncio.run(scenario())
    # (2) the original exception still propagates
    assert exception_raised is not None
    assert "Summarizer failed" in str(exception_raised)
    # (1) transcript survives the summarizer failure (spec §9)
    assert len(segments) == 2
    assert {s.text for s in segments} == {"Selamat pagi", "Mari kita mulai"}
    # (3) meeting status is "failed"
    assert meetings[0].status == "failed"
    # (4) a Summary row exists with status="failed"
    assert len(summaries) == 1
    assert summaries[0].status == "failed"
    assert summaries[0].docx_path is None


def test_finalize_meeting_clears_existing_drafts_before_saving_final_segments(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

        # Simulate a leftover live-preview draft from before Stop was clicked.
        async with session_factory() as session:
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 400, "text": "draft yang belum sempat dihapus",
                 "is_final": False},
            ])
            await session.commit()

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()
        docx_path = tmp_path / "mom.docx"

        transcriber_calls = {"mic.wav": [
            TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")
        ], "speaker.wav": [
            TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")
        ]}

        class RoutingFakeTranscriber:
            def transcribe(self, wav_path, language="id"):
                return transcriber_calls[wav_path.name]

        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])
        summarizer = FakeSummarizer()

        async with session_factory() as session:
            await finalize_meeting(
                session=session, meeting_id=meeting_id, meeting_title="Rapat Uji",
                meeting_date=datetime(2026, 7, 30, 9, 0), mic_wav=mic_wav, speaker_wav=speaker_wav,
                transcriber=RoutingFakeTranscriber(), diarizer=diarizer, summarizer=summarizer,
                docx_output_path=docx_path,
            )
            await session.commit()

        async with session_factory() as session:
            result = await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )
            return result.scalars().all()

    segments = asyncio.run(scenario())
    texts = {seg.text for seg in segments}
    assert "draft yang belum sempat dihapus" not in texts
    assert all(seg.is_final for seg in segments)
    assert "Selamat pagi" in texts


def test_finalize_meeting_reports_progress_through_each_stage(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        transcriber_calls = {"mic.wav": [
            TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")
        ], "speaker.wav": [
            TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")
        ]}

        class RoutingFakeTranscriber:
            def transcribe(self, wav_path, language="id"):
                return transcriber_calls[wav_path.name]

        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])
        summarizer = FakeSummarizer()
        steps = []

        async with session_factory() as session:
            await finalize_meeting(
                session=session, meeting_id=meeting_id, meeting_title="Rapat Uji",
                meeting_date=datetime(2026, 7, 30, 9, 0), mic_wav=mic_wav, speaker_wav=speaker_wav,
                transcriber=RoutingFakeTranscriber(), diarizer=diarizer, summarizer=summarizer,
                docx_output_path=tmp_path / "mom.docx", on_progress=steps.append,
            )
            await session.commit()
        return steps

    steps = asyncio.run(scenario())
    assert steps == [
        "Transkrip mic...", "Transkrip speaker...", "Diarisasi speaker...",
        "Membuat ringkasan (Groq)...", "Ekspor docx...",
    ]
