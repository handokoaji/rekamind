from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Job, Meeting

ACTIVE = ("queued", "running")


async def enqueue(sf: async_sessionmaker[AsyncSession], meeting_id: str, kind: str = "process") -> Job:
    """Idempotent: a double-click on "Proses" returns the job already in flight."""
    async with sf() as s:
        existing = (
            await s.execute(select(Job).where(Job.meeting_id == meeting_id, Job.kind == kind, Job.status.in_(ACTIVE)))
        ).scalars().first()
        if existing:
            return existing
        job = Job(meeting_id=meeting_id, kind=kind)
        s.add(job)
        await s.execute(update(Meeting).where(Meeting.id == meeting_id).values(status="queued", error=None))
        await s.commit()
        return job


async def claim_next(sf: async_sessionmaker[AsyncSession]) -> Job | None:
    """Atomically take the oldest queued job. The conditional UPDATE is the lock:
    when two workers race for the same row, exactly one sees rowcount == 1."""
    while True:
        async with sf() as s:
            job_id = (
                await s.execute(select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(1))
            ).scalar()
            if job_id is None:
                return None
            res = await s.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(status="running", claimed_at=datetime.now(UTC), attempts=Job.attempts + 1)
            )
            await s.commit()
            if res.rowcount == 1:
                return await s.get(Job, job_id)


async def set_progress(sf: async_sessionmaker[AsyncSession], job_id: str, stage: str, progress: int) -> None:
    async with sf() as s:
        await s.execute(update(Job).where(Job.id == job_id).values(stage=stage, progress=progress))
        await s.commit()


async def finish(sf: async_sessionmaker[AsyncSession], job_id: str, error: str | None = None) -> None:
    async with sf() as s:
        await s.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="failed" if error else "done",
                error=error,
                progress=100 if not error else Job.progress,
                finished_at=datetime.now(UTC),
            )
        )
        await s.commit()


MAX_ATTEMPTS = 3


async def recover_abandoned(sf: async_sessionmaker[AsyncSession]) -> int:
    """At startup, a job still 'running' means the process died mid-job.
    Requeue it instead of leaving the meeting stuck forever -- but a job that has
    already killed the process MAX_ATTEMPTS times (native crash on bad audio, OOM)
    is failed, otherwise it would crash-loop the worker indefinitely."""
    async with sf() as s:
        poisoned = (await s.execute(select(Job).where(Job.status == "running", Job.attempts >= MAX_ATTEMPTS))).scalars().all()
        for j in poisoned:
            j.status, j.finished_at = "failed", datetime.now(UTC)
            j.error = f"Pemrosesan berhenti tiba-tiba {j.attempts}x (kemungkinan file audio bermasalah atau memori habis)"
            m = await s.get(Meeting, j.meeting_id)
            if m:
                m.status, m.error = "failed", j.error
        res = await s.execute(update(Job).where(Job.status == "running").values(status="queued", stage=None, progress=0))
        await s.commit()
        return res.rowcount
