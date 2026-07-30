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


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
