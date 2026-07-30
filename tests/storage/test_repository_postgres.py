"""Integration test against the real Postgres server.

SQLite-only testing hid two production-fatal bugs (tz-aware datetimes into naive
TIMESTAMP columns, and pooled asyncpg connections dying across asyncio.run()
calls). This exercises the full lifecycle on the real backend so they can't
come back. Skipped by default; run with `pytest -m postgres`.
"""

import asyncio

import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.storage import repository as repo
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.models import Meeting, Recording, Speaker, Summary, TranscriptSegment

pytestmark = pytest.mark.postgres


async def _cleanup(session_factory, meeting_id: int) -> None:
    async with session_factory() as session:
        # FK order: segments reference speakers, everything references meetings.
        for model in (Summary, TranscriptSegment, Recording, Speaker):
            await session.execute(delete(model).where(model.meeting_id == meeting_id))
        await session.execute(delete(Meeting).where(Meeting.id == meeting_id))
        await session.commit()


def test_full_lifecycle_against_real_postgres():
    engine = make_engine(get_settings().database_url)
    # init_db in its own asyncio.run(), like app.main does -- the later run()s
    # below are what broke with a pooled connection (C2).
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    async def create():
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Integrasi", None)
            await repo.start_recording(session, meeting.id)
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(create())

    try:
        async def lifecycle():
            async with session_factory() as session:
                speaker = await repo.get_or_create_speaker(session, meeting_id, "Speaker 1")
                await repo.save_transcript_segments(session, [
                    {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                     "start_ms": 0, "end_ms": 500, "text": "Selamat pagi"},
                    {"meeting_id": meeting_id, "speaker_id": speaker.id, "source": "speaker",
                     "start_ms": 600, "end_ms": 1500, "text": "Mari kita mulai"},
                ])
                await repo.stop_recording(session, meeting_id)
                await repo.save_recording_file(
                    session, meeting_id, "./recordings/x/mic.wav", "mic", 1500
                )
                await repo.save_summary(
                    session, meeting_id, mom_json="{}", docx_path=None,
                    groq_model="llama-3.3-70b-versatile", status="ready",
                )
                await repo.mark_meeting_status(session, meeting_id, "completed")
                await session.commit()

        asyncio.run(lifecycle())

        async def read_back():
            async with session_factory() as session:
                meetings = await repo.list_meetings(session)
                return [m for m in meetings if m.id == meeting_id]

        rows = asyncio.run(read_back())
        assert len(rows) == 1
        assert rows[0].status == "completed"
        # C1: these round-trip only if the columns are timestamptz.
        assert rows[0].created_at.tzinfo is not None
        assert rows[0].start_time is not None
        assert rows[0].end_time is not None
    finally:
        asyncio.run(_cleanup(session_factory, meeting_id))
        asyncio.run(engine.dispose())
