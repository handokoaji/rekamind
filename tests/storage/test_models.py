import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.storage.models import Base, Meeting, Speaker, TranscriptSegment, Recording, Summary


async def _make_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def test_meeting_with_related_rows_round_trips():
    async def scenario() -> int:
        session_factory = await _make_session_factory()
        async with session_factory() as session:
            meeting = Meeting(title="Standup", status="recording")
            session.add(meeting)
            await session.flush()

            speaker = Speaker(meeting_id=meeting.id, label="Speaker 1")
            session.add(speaker)
            await session.flush()

            session.add(TranscriptSegment(
                meeting_id=meeting.id, speaker_id=speaker.id,
                source="speaker", start_ms=0, end_ms=1000, text="halo semua",
            ))
            session.add(Recording(
                meeting_id=meeting.id, file_path="./recordings/1/speaker.wav",
                source="speaker", duration_ms=1000,
            ))
            session.add(Summary(
                meeting_id=meeting.id, mom_json="{}", groq_model="llama-3.3-70b-versatile",
                status="pending",
            ))
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(scenario())
    assert isinstance(meeting_id, int)
