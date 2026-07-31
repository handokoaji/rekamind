import asyncio
from datetime import datetime

from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.summarization.groq_client import MomResult
from app.pipeline.summarize import summarize_and_export


class FakeSummarizer:
    model = "llama-3.3-70b-versatile"

    def summarize(self, meeting_title, transcript_text):
        assert "Anda" in transcript_text
        return MomResult(
            minute_by_minute=[{"time": "00:00", "point": "Mulai"}],
            decisions=["Lanjut"], action_items=[], detailed_notes="Catatan.",
        )


class FailingSummarizer:
    model = "llama-3.3-70b-versatile"

    def summarize(self, meeting_title, transcript_text):
        raise RuntimeError("Groq timeout")


async def _seed_transcribed_meeting(session_factory, title="Rapat Uji"):
    async with session_factory() as session:
        meeting = await repo.create_meeting(session, title, None)
        await session.commit()
        meeting_id = meeting.id
        await repo.save_transcript_segments(session, [
            {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
             "start_ms": 0, "end_ms": 500, "text": "Selamat pagi"},
        ])
        await repo.mark_meeting_status(session, meeting_id, "transcribed")
        await session.commit()
    return meeting_id


def test_summarize_and_export_reads_transcript_from_db_and_completes(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        meeting_id = await _seed_transcribed_meeting(session_factory)

        docx_path = tmp_path / "mom.docx"
        summary = await summarize_and_export(
            session_factory, meeting_id, "Rapat Uji", datetime(2026, 7, 31, 9, 0),
            docx_path, FakeSummarizer(),
        )

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return summary, meetings, docx_path.exists()

    summary, meetings, docx_exists = asyncio.run(scenario())
    assert summary.status == "ready"
    assert meetings[0].status == "completed"
    assert docx_exists is True


def test_summarize_and_export_marks_failed_on_summarizer_error(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        meeting_id = await _seed_transcribed_meeting(session_factory)

        exception_raised = None
        try:
            await summarize_and_export(
                session_factory, meeting_id, "Rapat Uji", datetime(2026, 7, 31, 9, 0),
                tmp_path / "mom.docx", FailingSummarizer(),
            )
        except RuntimeError as e:
            exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return exception_raised, meetings, segments

    exception_raised, meetings, segments = asyncio.run(scenario())
    assert exception_raised is not None
    assert meetings[0].status == "failed"
    assert meetings[0].failed_stage == "summarize"
    assert "Groq timeout" in meetings[0].error_message
    # the transcript from the earlier transcribe stage must survive intact
    assert len(segments) == 1
