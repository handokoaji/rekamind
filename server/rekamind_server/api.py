import asyncio
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import __version__, jobs
from .audio import UnsupportedAudio, is_wav, to_wav_16k_mono
from .config import Settings
from .db import init_db, make_engine, make_session_factory
from .engines.base import Engines
from .engines.registry import build_engines
from .models import Job, Meeting, Participant, Task
from .schemas import (
    JobBrief,
    JobOut,
    MeetingCreate,
    MeetingDetail,
    MeetingPatch,
    MeetingSummaryOut,
    ParticipantOut,
    ParticipantPatch,
    TaskOut,
    TaskPatch,
    TaskWithMeeting,
)
from .storage import LocalStorage, S3Storage, Storage
from .worker import Worker


def build_storage(settings: Settings) -> Storage:
    if settings.storage == "local":
        return LocalStorage(settings.data_dir)
    if settings.storage == "s3":
        if not (settings.s3_access_key and settings.s3_secret_key):
            raise ValueError("REKAMIND_S3_ACCESS_KEY dan REKAMIND_S3_SECRET_KEY wajib diisi untuk storage s3")
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url, bucket=settings.s3_bucket, access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key, region=settings.s3_region, prefix=settings.s3_prefix,
            cache_dir=settings.data_dir / "cache", path_style=settings.s3_path_style,
        )
    raise ValueError(f"REKAMIND_STORAGE='{settings.storage}' tidak dikenal (local | s3)")


def create_app(settings: Settings | None = None, *, engines: Engines | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.effective_database_url)
        await init_db(engine)
        app.state.sf = make_session_factory(engine)
        storage = build_storage(settings)
        if isinstance(storage, S3Storage) and settings.s3_create_bucket:
            await asyncio.to_thread(storage.ensure_bucket)
        if isinstance(storage, S3Storage):
            shutil.rmtree(settings.data_dir / "cache", ignore_errors=True)  # only ever a cache; crashes can strand copies
        app.state.storage = storage
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
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

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
                    started_at=body.started_at or datetime.now(UTC))
        db.add(m)
        await db.commit()
        return m

    @app.get("/api/meetings", response_model=list[MeetingSummaryOut])
    async def list_meetings(db: Db, limit: int = 50, offset: int = 0, q: str | None = None, status: str | None = None):
        query = select(Meeting).where(Meeting.deleted_at.is_(None))
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Meeting.title.ilike(f"%{escaped}%", escape="\\"))
        if status:
            query = query.where(Meeting.status == status)
        rows = (await db.execute(query.order_by(Meeting.started_at.desc()).limit(min(limit, 200)).offset(offset))).scalars().all()
        active = (await db.execute(select(Job).where(Job.meeting_id.in_([m.id for m in rows]), Job.status.in_(jobs.ACTIVE))
                                   .order_by(Job.created_at))).scalars().all() if rows else []
        by_meeting = {j.meeting_id: JobBrief.model_validate(j) for j in active}
        return [MeetingSummaryOut.model_validate(m).model_copy(update={"job": by_meeting.get(m.id)}) for m in rows]

    @app.get("/api/meetings/{meeting_id}", response_model=MeetingDetail)
    async def get_meeting(meeting_id: str, db: Db):
        return await _meeting(db, meeting_id)

    @app.patch("/api/meetings/{meeting_id}", response_model=MeetingSummaryOut)
    async def rename_meeting(meeting_id: str, body: MeetingPatch, db: Db):
        m = await _meeting(db, meeting_id)
        m.title = body.title.strip()
        await db.commit()
        return m

    @app.post("/api/meetings/{meeting_id}/restore", response_model=MeetingSummaryOut)
    async def restore_meeting(meeting_id: str, db: Db):
        m = await db.get(Meeting, meeting_id)
        if m is None:
            raise HTTPException(404, "Rapat tidak ditemukan")
        m.deleted_at = None
        await db.commit()
        return m

    @app.get("/api/meetings/{meeting_id}/audio/{source}")
    async def get_audio(meeting_id: str, source: Literal["mic", "speaker"], request: Request, db: Db):
        await _meeting(db, meeting_id)
        path = await request.app.state.storage.audio_path(meeting_id, source)
        if path is None:
            raise HTTPException(404, "Audio tidak tersedia")
        return FileResponse(path, media_type="audio/wav")  # Starlette serves Range requests, so seeking works

    @app.delete("/api/meetings/{meeting_id}", status_code=204)
    async def delete_meeting(meeting_id: str, db: Db):
        m = await _meeting(db, meeting_id)
        m.deleted_at = datetime.now(UTC)  # soft delete: undoable, and safe against sync resurrection
        await db.commit()

    @app.put("/api/meetings/{meeting_id}/audio/{source}", status_code=201)
    async def upload_audio(meeting_id: str, source: Literal["mic", "speaker"], request: Request, db: Db):
        await _meeting(db, meeting_id)
        tmp_dir = settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        raw = tmp_dir / f"{uuid.uuid4().hex}.upload"
        wav = raw.with_suffix(".wav")
        limit = settings.max_upload_mb * 1024 * 1024
        try:
            size = 0
            with raw.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"File melebihi batas {settings.max_upload_mb} MB")
                    f.write(chunk)
            if size == 0:
                raise HTTPException(400, "File audio kosong")
            final = raw
            if not is_wav(raw):
                try:
                    await asyncio.to_thread(to_wav_16k_mono, raw, wav)
                except UnsupportedAudio as exc:
                    raise HTTPException(415, str(exc)) from exc
                final = wav

            async def chunks():
                with final.open("rb") as f:
                    while block := f.read(1024 * 1024):
                        yield block

            stored = await request.app.state.storage.save_audio(meeting_id, source, chunks())
            return {"bytes": stored}
        finally:
            raw.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)

    @app.post("/api/meetings/{meeting_id}/finish", response_model=MeetingSummaryOut)
    async def finish_meeting(meeting_id: str, db: Db):
        m = await _meeting(db, meeting_id)
        if m.status != "recording":
            raise HTTPException(409, "Rapat tidak sedang direkam")
        m.status, m.ended_at = "recorded", datetime.now(UTC)
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

    @app.get("/api/tasks", response_model=list[TaskWithMeeting])
    async def list_tasks(db: Db, status: Literal["suggested", "confirmed", "rejected"] | None = None,
                         meeting_id: str | None = None):
        q = (select(Task, Meeting.title).join(Meeting, Meeting.id == Task.meeting_id)
             .where(Meeting.deleted_at.is_(None)).order_by(Task.created_at))
        if status:
            q = q.where(Task.status == status)
        if meeting_id:
            q = q.where(Task.meeting_id == meeting_id)
        return [TaskWithMeeting(**TaskOut.model_validate(t).model_dump(), meeting_title=title)
                for t, title in (await db.execute(q)).all()]

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
        await db.flush()
        m = await db.get(Meeting, t.meeting_id)
        if m and m.status in ("review", "done"):
            pending = (await db.execute(select(Task.id).where(Task.meeting_id == t.meeting_id, Task.status == "suggested").limit(1))).first()
            m.status = "review" if pending else "done"  # finishing the review is visible, undoing it re-opens it
        await db.commit()
        return t

    if settings.web_dir and (web := Path(settings.web_dir)).is_dir():
        # Registered last so every /api route wins. Unknown paths fall back to index.html
        # so client-side routes survive a browser refresh.
        class SpaFiles(StaticFiles):
            async def get_response(self, path, scope):
                try:
                    return await super().get_response(path, scope)
                except Exception:
                    if path.startswith("api/"):
                        raise
                    return await super().get_response("index.html", scope)

        app.mount("/", SpaFiles(directory=web, html=True), name="web")
    return app
