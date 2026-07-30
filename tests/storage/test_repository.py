import asyncio
import pytest
from datetime import datetime, timezone

from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo


def test_full_meeting_lifecycle():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Sprint Review", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.start_recording(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            speaker = await repo.get_or_create_speaker(session, meeting_id, "Speaker 1")
            await session.commit()
            speaker_id = speaker.id

        async with session_factory() as session:
            await repo.save_recording_file(session, meeting_id, "./recordings/1/mic.wav", "mic", 5000)
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 900, "text": "Selamat pagi"},
                {"meeting_id": meeting_id, "speaker_id": speaker_id, "source": "speaker",
                 "start_ms": 900, "end_ms": 2000, "text": "Pagi, mulai ya"},
            ])
            await repo.stop_recording(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            summary = await repo.save_summary(
                session, meeting_id, mom_json="{\"catatan\": \"ok\"}",
                docx_path="./recordings/1/mom.docx", groq_model="llama-3.3-70b-versatile",
                status="ready",
            )
            await repo.mark_meeting_status(session, meeting_id, "completed")
            await session.commit()
            summary_id = summary.id

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)

        return meeting_id, summary_id, meetings

    meeting_id, summary_id, meetings = asyncio.run(scenario())
    assert isinstance(meeting_id, int)
    assert isinstance(summary_id, int)
    assert len(meetings) == 1
    assert meetings[0].status == "completed"
    assert meetings[0].start_time is not None
    assert meetings[0].end_time is not None


def test_start_recording_missing_meeting():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            try:
                await repo.start_recording(session, 999)
                return False
            except ValueError as e:
                return "Meeting 999 not found" in str(e)

    result = asyncio.run(scenario())
    assert result is True


def test_stop_recording_missing_meeting():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            try:
                await repo.stop_recording(session, 999)
                return False
            except ValueError as e:
                return "Meeting 999 not found" in str(e)

    result = asyncio.run(scenario())
    assert result is True


def test_mark_meeting_status_missing_meeting():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            try:
                await repo.mark_meeting_status(session, 999, "failed")
                return False
            except ValueError as e:
                return "Meeting 999 not found" in str(e)

    result = asyncio.run(scenario())
    assert result is True
