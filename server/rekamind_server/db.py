from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
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
        engine = create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        engine = create_async_engine(url)
    if url.startswith("sqlite"):
        # SQLite ignores foreign keys unless asked. Postgres always enforces them, so without this a
        # constraint bug only shows up in production on the other database.
        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_connection, _record):  # noqa: ANN001
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
    return engine


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
