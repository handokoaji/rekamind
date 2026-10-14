from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

_MIGRATIONS = Path(__file__).parent / "migrations"
_LOCK_KEY = 0x52454B41  # arbitrary constant: "REKA"


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite") and ":memory:" in url:
        # One shared connection, otherwise every checkout sees its own empty DB.
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_async_engine(url)


def alembic_config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def _run(connection, fn, revision: str) -> None:
    if connection.dialect.name == "postgresql":
        # API and a standalone worker may start together; only one may migrate at a time.
        connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    fn(alembic_config(connection), revision)


async def migrate(engine: AsyncEngine, revision: str = "head") -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_run, command.upgrade, revision)


async def downgrade(engine: AsyncEngine, revision: str = "base") -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_run, command.downgrade, revision)


init_db = migrate  # name kept for callers/tests; there is no create_all path anymore


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
