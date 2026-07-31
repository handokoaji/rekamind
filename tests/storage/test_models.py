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


def test_meeting_device_fields_default_to_none():
    meeting = Meeting(title="Rapat", device_id=None, device_label=None)
    assert meeting.device_id is None
    assert meeting.device_label is None


def test_meeting_accepts_device_fields():
    meeting = Meeting(title="Rapat", device_id="abc123", device_label="Laptop Budi")
    assert meeting.device_id == "abc123"
    assert meeting.device_label == "Laptop Budi"


def test_meeting_synced_at_defaults_to_none():
    meeting = Meeting(title="Rapat")
    assert meeting.synced_at is None


def test_meeting_accepts_synced_at():
    from datetime import datetime, timezone
    ts = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    meeting = Meeting(title="Rapat", synced_at=ts)
    assert meeting.synced_at == ts


def test_meeting_failure_fields_round_trip():
    async def scenario():
        session_factory = await _make_session_factory()
        async with session_factory() as session:
            meeting = Meeting(
                title="Standup", status="failed",
                failed_stage="transcribe", error_message="CUDA out of memory",
            )
            session.add(meeting)
            await session.commit()
            return meeting.id

        return meeting.id

    meeting_id = asyncio.run(scenario())
    assert isinstance(meeting_id, int)
