import asyncio

from sqlalchemy import text

from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.models import Meeting


def test_init_db_adds_missing_columns_to_an_existing_table():
    """Regression test: Base.metadata.create_all only creates missing TABLES,
    never adds columns to a table that already exists -- an existing install
    upgrading past a schema change (e.g. the device_id/device_label/synced_at
    columns added for multi-device sync) would otherwise break with "no such
    column" on every query. Simulate an old install by creating the
    `meetings` table without those columns, then confirm init_db() adds them."""
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE meetings ("
                "id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, "
                "scheduled_time DATETIME, start_time DATETIME, end_time DATETIME, "
                "status VARCHAR NOT NULL, created_at DATETIME NOT NULL, "
                "recording_dir VARCHAR, error_message VARCHAR, failed_stage VARCHAR"
                ")"
            ))

        await init_db(engine)

        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            meeting = Meeting(title="Rapat A", status="scheduled", device_id="dev1", device_label="PC-1")
            session.add(meeting)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            result = await session.get(Meeting, meeting_id)
            return result.device_id, result.device_label, result.synced_at

    device_id, device_label, synced_at = asyncio.run(scenario())
    assert device_id == "dev1"
    assert device_label == "PC-1"
    assert synced_at is None


def test_init_db_is_idempotent_on_a_fresh_database():
    """A brand-new install has no pre-existing tables at all -- create_all
    handles that case fully already, but the added column-backfill step must
    not choke on it (e.g. by assuming every table in Base.metadata already
    exists)."""
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        await init_db(engine)  # must not raise the second time either

        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            meeting = Meeting(title="Rapat B", status="scheduled")
            session.add(meeting)
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(scenario())
    assert meeting_id is not None
