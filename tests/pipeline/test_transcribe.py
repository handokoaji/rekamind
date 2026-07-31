import asyncio
from datetime import datetime

from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment
from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.storage.models import TranscriptSegment
from app.pipeline.transcribe import transcribe_and_diarize


class RoutingFakeTranscriber:
    def __init__(self, by_filename):
        self._by_filename = by_filename

    def transcribe(self, wav_path, language="id"):
        return self._by_filename[wav_path.name]


class FakeDiarizer:
    def __init__(self, labels):
        self._labels = labels

    def diarize(self, wav_path):
        return self._labels


class ExplodingTranscriber:
    def transcribe(self, wav_path, language="id"):
        raise RuntimeError("CUDA out of memory")


def test_transcribe_and_diarize_saves_final_segments_and_marks_transcribed(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await repo.mark_meeting_status(session, meeting.id, "recorded")
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        transcriber = RoutingFakeTranscriber({
            "mic.wav": [TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")],
            "speaker.wav": [TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")],
        })
        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])

        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, diarizer)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            from sqlalchemy import select
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return meetings, segments

    meetings, segments = asyncio.run(scenario())
    assert meetings[0].status == "transcribed"
    assert {s.text for s in segments} == {"Selamat pagi", "Mari kita mulai"}
    assert all(s.is_final for s in segments)


def test_transcribe_and_diarize_marks_failed_on_transcriber_error(tmp_path):
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

        exception_raised = None
        try:
            await transcribe_and_diarize(
                session_factory, meeting_id, mic_wav, speaker_wav,
                ExplodingTranscriber(), FakeDiarizer([]),
            )
        except RuntimeError as e:
            exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return exception_raised, meetings

    exception_raised, meetings = asyncio.run(scenario())
    assert exception_raised is not None
    assert "CUDA out of memory" in str(exception_raised)
    assert meetings[0].status == "failed"
    assert meetings[0].failed_stage == "transcribe"
    assert "CUDA out of memory" in meetings[0].error_message


def test_running_transcribe_twice_leaves_exactly_one_set_of_segments(tmp_path):
    """clear_draft_segments only removed is_final=False rows, so a retry (or a
    double-click) appended a second copy of the transcript next to the first --
    which then doubled the text sent to Groq in the next stage."""
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await repo.mark_meeting_status(session, meeting.id, "recorded")
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        transcriber = RoutingFakeTranscriber({
            "mic.wav": [TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")],
            "speaker.wav": [TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")],
        })
        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])

        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, diarizer)
        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, diarizer)

        async with session_factory() as session:
            from sqlalchemy import select
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
            meetings = await repo.list_meetings(session)
        return segments, meetings

    segments, meetings = asyncio.run(scenario())
    assert len(segments) == 2, f"expected one set of 2 segments, got {[s.text for s in segments]}"
    assert sorted(s.text for s in segments) == ["Mari kita mulai", "Selamat pagi"]
    assert meetings[0].status == "transcribed"


def test_transcribe_and_diarize_clears_existing_drafts_first(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 400, "text": "draft belum sempat dihapus", "is_final": False},
            ])
            await session.commit()

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        transcriber = RoutingFakeTranscriber({
            "mic.wav": [TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")],
            "speaker.wav": [],
        })
        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, FakeDiarizer([]))

        async with session_factory() as session:
            from sqlalchemy import select
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return segments

    segments = asyncio.run(scenario())
    texts = {s.text for s in segments}
    assert "draft belum sempat dihapus" not in texts
    assert "Selamat pagi" in texts
