"""Permanent deletion. "Delete" in the UI is a soft delete (undoable); this is what makes it final."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Job, Meeting, Participant, Segment, Summary, Task
from .storage import Storage

log = logging.getLogger(__name__)


class Busy(Exception):
    """The meeting is being processed right now; deleting its audio under the worker would corrupt the job."""


async def purge_meeting(db: AsyncSession, storage: Storage, meeting: Meeting) -> None:
    running = (await db.execute(select(Job.id).where(Job.meeting_id == meeting.id, Job.status == "running"))).first()
    if running:
        raise Busy
    # Files first: if that fails the row stays, so the purge can simply be retried.
    await storage.delete_audio(meeting.id)
    # Children before parents, explicitly: segments and tasks point at participants, and Postgres (unlike
    # SQLite without foreign_keys) refuses to delete a participant that something still references.
    for model in (Task, Segment, Summary, Job, Participant):
        await db.execute(delete(model).where(model.meeting_id == meeting.id))
    await db.execute(delete(Meeting).where(Meeting.id == meeting.id))
    db.expunge(meeting)
    await db.commit()


async def purge_expired(sf: async_sessionmaker[AsyncSession], storage: Storage, days: int) -> int:
    """Permanently remove meetings that have sat in the trash longer than `days`. 0 disables."""
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    done = 0
    async with sf() as db:
        old = (await db.execute(select(Meeting).where(Meeting.deleted_at.is_not(None), Meeting.deleted_at < cutoff))).scalars().all()
        for m in old:
            try:
                await purge_meeting(db, storage, m)
                done += 1
            except Busy:
                continue
            except Exception:  # noqa: BLE001 - one bad meeting must not stop the sweep
                log.exception("could not purge meeting %s", m.id)
                await db.rollback()
    return done


async def sweep_forever(sf: async_sessionmaker[AsyncSession], storage: Storage, days: int, every: float = 3600.0,
                        first_after: float = 60.0) -> None:
    await asyncio.sleep(first_after)  # never compete with start-up work
    while True:
        try:
            n = await purge_expired(sf, storage, days)
            if n:
                log.info("purged %d meetings from the trash", n)
        except Exception:  # noqa: BLE001
            log.exception("trash sweep failed")
        await asyncio.sleep(every)
