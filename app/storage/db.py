from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.storage.models import Base


def make_engine(database_url: str) -> AsyncEngine:
    # NullPool: the app calls asyncio.run() more than once (startup init_db, then
    # each start/stop click). A pooled asyncpg connection is bound to the loop
    # that created it, so a reused connection would be dead on the next
    # asyncio.run(). No pooling = a fresh connection per session, always valid.
    # Exception: sqlite ":memory:" IS its connection -- NullPool would hand out a
    # fresh empty database every time, so leave the sqlite default pool alone.
    if database_url.startswith("sqlite"):
        return create_async_engine(database_url)
    return create_async_engine(database_url, poolclass=NullPool)


def _existing_columns_by_table(sync_conn) -> dict[str, set[str]]:
    inspector = inspect(sync_conn)
    return {
        table.name: {col["name"] for col in inspector.get_columns(table.name)}
        for table in Base.metadata.sorted_tables
        if inspector.has_table(table.name)
    }


async def _add_missing_columns(engine: AsyncEngine) -> None:
    """create_all only creates missing TABLES -- it never adds a column to a
    table that already exists, so an existing install upgrading past a schema
    change would break with "no such column" on every query. Every column
    this app has ever added is nullable with no server-side default, so a
    bare ADD COLUMN (no backfill needed) is always valid on both sqlite and
    Postgres."""
    async with engine.begin() as conn:
        existing_by_table = await conn.run_sync(_existing_columns_by_table)
        for table in Base.metadata.sorted_tables:
            existing = existing_by_table.get(table.name)
            if existing is None:
                continue  # brand-new table -- create_all already made it in full
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=conn.dialect)
                await conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl_type}"))


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _add_missing_columns(engine)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
