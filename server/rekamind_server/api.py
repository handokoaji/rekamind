import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from . import __version__, jobs
from .config import Settings
from .db import init_db, make_engine, make_session_factory
from .engines.base import Engines
from .engines.registry import build_engines
from .models import Job, Meeting, Participant, Task
from .schemas import (JobOut, MeetingCreate, MeetingDetail, MeetingSummaryOut, ParticipantOut, ParticipantPatch,
                      TaskOut, TaskPatch)
from .storage import LocalStorage, Storage
from .worker import Worker


def create_app(settings: Settings | None = None, *, engines: Engines | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.effective_database_url)
        await init_db(engine)
        app.state.sf = make_session_factory(engine)
        app.state.storage = LocalStorage(settings.data_dir)
        app.state.engines = engines if engines is not None else build_engines(settings)
        task = None
        if settings.worker_inprocess and app.state.engines:
            worker = Worker(app.state.sf, app.state.storage, app.state.engines, settings.worker_poll_seconds)
            task = asyncio.create_task(worker.run_forever())
        yield
        if task:
            task.cancel()
        await engine.dispose()

    app = FastAPI(title="Rekamind", version=__version__, lifespan=lifespan)

    async def session(request: Request):
        async with request.app.state.sf() as s:
            yield s

    Db = Annotated[AsyncSession, Depends(session)]

    def storage(request: Request) -> Storage:
        return request.app.state.storage

    async def _meeting(db: AsyncSession, meeting_id: str) -> Meeting:
        m = (await db.execute(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None)).options(
                selectinload(Meeting.participants), selectinload(Meeting.segments),
                selectinload(Meeting.tasks), selectinload(Meeting.summary))
        )).scalar()
        if m is None:
            raise HTTPException(404, "Rapat tidak ditemukan")
        return m

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/capabilities")
    async def capabilities(request: Request):
        e: Engines | None = request.app.state.engines
        return {"processing_ready": e is not None, "engines": e.description if e else {}}

    @app.post("/api/meetings", status_code=201, response_model=MeetingSummaryOut)
    async def create_meeting(body: MeetingCreate, db: Db):
        m = Meeting(title=body.title, language=body.language, local_user_name=body.local_user_name,
                    started_at=body.started_at or datetime.now(timezone.utc))
        db.add(m)
        await db.commit()
        return m

    @app.get("/api/meetings", response_model=list[MeetingSummaryOut])
    async def list_meetings(db: Db, limit: int = 50, offset: int = 0):
        rows = await db.execute(select(Meeting).where(Meeting.deleted_at.is_(None))
                                .order_by(Meeting.started_at.desc()).limit(min(limit, 200)).offset(offset))
        return rows.scalars().all()

    @app.get("/api/meetings/{meeting_id}", response_model=MeetingDetail)
    async def get_meeting(meeting_id: str, db: Db):
        return await _meeting(db, meeting_id)

    @app.delete("/api/meetings/{meeting_id}", status_code=204)
    async def delete_meeting(meeting_id: str, db: Db):
        m = await _meeting(db, meeting_id)
        m.deleted_at = datetime.now(timezone.utc)  # soft delete: undoable, and safe against sync resurrection
        await db.commit()

    @app.put("/api/meetings/{meeting_id}/audio/{source}", status_code=201)
    async def upload_audio(meeting_id: str, source: Literal["mic", "speaker"], request: Request, db: Db):
        await _meeting(db, meeting_id)
        size = await request.app.state.storage.save_audio(meeting_id, source, request.stream())
        if size == 0:
            raise HTTPException(400, "File audio kosong")
        return {"bytes": size}

    @app.post("/api/meetings/{meeting_id}/finish", response_model=MeetingSummaryOut)
    async def finish_meeting(meeting_id: str, db: Db):
        m = await _meeting(db, meeting_id)
        if m.status != "recording":
            raise HTTPException(409, "Rapat tidak sedang direkam")
        m.status, m.ended_at = "recorded", datetime.now(timezone.utc)
        await db.commit()
        return m

    @app.post("/api/meetings/{meeting_id}/process", status_code=202, response_model=JobOut)
    async def process_meeting(meeting_id: str, request: Request, db: Db):
        if request.app.state.engines is None:
            raise HTTPException(503, "Mesin pemrosesan belum dikonfigurasi di backend ini")
        m = await _meeting(db, meeting_id)
        if m.status == "recording":
            raise HTTPException(409, "Selesaikan perekaman dulu sebelum memproses")
        return await jobs.enqueue(request.app.state.sf, meeting_id)

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    async def get_job(job_id: str, db: Db):
        j = await db.get(Job, job_id)
        if j is None:
            raise HTTPException(404, "Job tidak ditemukan")
        return j

    @app.patch("/api/participants/{participant_id}", response_model=ParticipantOut)
    async def rename_participant(participant_id: str, body: ParticipantPatch, db: Db):
        p = await db.get(Participant, participant_id)
        if p is None:
            raise HTTPException(404, "Pembicara tidak ditemukan")
        p.name = (body.name or "").strip() or None
        await db.commit()
        return p

    @app.get("/api/tasks", response_model=list[TaskOut])
    async def list_tasks(db: Db, status: Literal["suggested", "confirmed", "rejected"] | None = None,
                         meeting_id: str | None = None):
        q = select(Task).order_by(Task.created_at)
        if status:
            q = q.where(Task.status == status)
        if meeting_id:
            q = q.where(Task.meeting_id == meeting_id)
        return (await db.execute(q)).scalars().all()

    @app.patch("/api/tasks/{task_id}", response_model=TaskOut)
    async def patch_task(task_id: str, body: TaskPatch, db: Db):
        t = await db.get(Task, task_id)
        if t is None:
            raise HTTPException(404, "Task tidak ditemukan")
        changes = body.model_dump(exclude_unset=True)
        if "assignee_participant_id" in changes and changes["assignee_participant_id"]:
            p = await db.get(Participant, changes["assignee_participant_id"])
            if p is None or p.meeting_id != t.meeting_id:  # can't assign to someone from another meeting
                raise HTTPException(422, "Pembicara bukan peserta rapat ini")
        if "deadline" in changes:
            changes["deadline_approximate"] = False  # a human-set date is a commitment
        for k, v in changes.items():
            setattr(t, k, v)
        await db.commit()
        return t

    return app
