from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from rekamind_server.db import downgrade, make_engine, migrate
from rekamind_server.models import Base

EXPECTED = {"meetings", "participants", "segments", "summaries", "tasks", "jobs"}


async def test_migrations_produce_exactly_the_schema_the_models_declare():
    """If someone edits models.py without writing a migration, this fails --
    the failure Alembic exists to prevent (works in dev, breaks on the server)."""
    e = make_engine("sqlite+aiosqlite:///:memory:")
    await migrate(e)
    async with e.connect() as conn:
        diff = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata))
    assert diff == [], f"models.py and migrations disagree: {diff}"


async def test_upgrade_is_idempotent_and_downgrade_removes_everything():
    e = make_engine("sqlite+aiosqlite:///:memory:")
    await migrate(e)
    await migrate(e)  # a second start must be a no-op, not an error
    async with e.connect() as conn:
        tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    assert EXPECTED <= tables

    await downgrade(e)
    async with e.connect() as conn:
        left = set(await conn.run_sync(lambda c: inspect(c).get_table_names())) - {"alembic_version"}
    assert left == set()


async def test_foreign_keys_and_indexes_survive_migration():
    e = make_engine("sqlite+aiosqlite:///:memory:")
    await migrate(e)
    async with e.connect() as conn:
        fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("segments"))
        idx = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("jobs")})
    assert {fk["referred_table"] for fk in fks} == {"meetings", "participants"}
    assert "ix_jobs_status_created" in idx
