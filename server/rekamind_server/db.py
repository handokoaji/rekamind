from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from .models import Base


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite") and ":memory:" in url:
        # One shared connection, otherwise every checkout sees its own empty DB.
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_async_engine(url)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
