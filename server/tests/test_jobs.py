import asyncio

from rekamind_server import jobs
from rekamind_server.db import init_db, make_engine, make_session_factory
from rekamind_server.models import Meeting


async def _sf():
    e = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(e)
    sf = make_session_factory(e)
    async with sf() as s:
        s.add(Meeting(id="a" * 32, title="x"))
        await s.commit()
    return sf


async def test_enqueue_is_idempotent():
    sf = await _sf()
    j1 = await jobs.enqueue(sf, "a" * 32)
    j2 = await jobs.enqueue(sf, "a" * 32)
    assert j1.id == j2.id


async def test_concurrent_claims_never_hand_out_the_same_job():
    sf = await _sf()
    await jobs.enqueue(sf, "a" * 32)
    got = await asyncio.gather(*(jobs.claim_next(sf) for _ in range(5)))
    assert len([j for j in got if j is not None]) == 1


async def test_recover_requeues_running_jobs():
    sf = await _sf()
    await jobs.enqueue(sf, "a" * 32)
    await jobs.claim_next(sf)
    assert await jobs.recover_abandoned(sf) == 1
    assert await jobs.claim_next(sf) is not None
