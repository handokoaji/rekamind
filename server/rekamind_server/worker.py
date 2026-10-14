import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import jobs
from .engines.base import Engines
from .models import Meeting
from .pipeline import run_process_job
from .storage import Storage

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, sf: async_sessionmaker[AsyncSession], storage: Storage, engines: Engines, poll: float = 1.0):
        self._sf, self._storage, self._engines, self._poll = sf, storage, engines, poll

    async def run_once(self) -> bool:
        job = await jobs.claim_next(self._sf)
        if job is None:
            return False
        async with self._sf() as s:
            m = await s.get(Meeting, job.meeting_id)
            if m:
                m.status = "processing"
                await s.commit()
        try:
            await run_process_job(self._sf, self._storage, self._engines, job)
            await jobs.finish(self._sf, job.id)
        except Exception as exc:  # the job fails, the worker loop must not
            log.exception("job %s failed", job.id)
            await jobs.finish(self._sf, job.id, error=str(exc))
            async with self._sf() as s:
                m = await s.get(Meeting, job.meeting_id)
                if m:
                    m.status, m.error = "failed", str(exc)
                    await s.commit()
        return True

    async def run_forever(self) -> None:
        await jobs.recover_abandoned(self._sf)
        worked = False
        while True:
            if await self.run_once():
                worked = True
            else:
                if worked and self._engines.release:
                    await asyncio.to_thread(self._engines.release)
                    worked = False
                await asyncio.sleep(self._poll)
