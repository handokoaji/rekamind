import asyncio
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import __version__, jobs, trash
from .audio import UnsupportedAudio, is_wav, to_wav_16k_mono
from .auth import routes as auth_routes
from .auth import service as auth_service
from .auth.deps import current_principal
from .auth.oidc import OidcClient
from .auth.service import Principal
from .config import Settings
from .db import init_db, make_engine, make_session_factory
from .engines.base import Engines
from .engines.registry import build_engines
from .models import Job, Meeting, Participant, Segment, Task
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



LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_auth_settings(s: Settings) -> None:
    """Refuse to start in a configuration that would leave the server open or unusable, with a message
    that says exactly what to set. Failing loudly at boot beats failing quietly in production."""
    if s.auth == "google":
        missing = [n for n, v in (("REKAMIND_GOOGLE_CLIENT_ID", s.google_client_id), ("REKAMIND_GOOGLE_CLIENT_SECRET", s.google_client_secret),
                                  ("REKAMIND_PUBLIC_URL", s.public_url), ("REKAMIND_SUPERADMINS", s.superadmins)) if not v.strip()]
        if missing:
            raise ValueError("Login Google butuh pengaturan: " + ", ".join(missing) + ". Buat OAuth client sendiri di Google Cloud Console (lihat docs/AUTH.md).")
        if not (s.public_url.startswith("https://") or s.public_url.startswith("http://localhost") or s.public_url.startswith("http://127.0.0.1")):
            raise ValueError("REKAMIND_PUBLIC_URL harus https:// (kecuali localhost untuk uji coba).")
        if s.signup not in ("allowlist", "open"):
            raise ValueError("REKAMIND_SIGNUP harus 'allowlist' atau 'open'.")
    elif s.auth == "local_token":
        if len(s.local_token) < 32:
            raise ValueError("REKAMIND_LOCAL_TOKEN wajib diisi, minimal 32 karakter acak.")
    elif s.auth == "none":
        if s.host not in LOOPBACK_HOSTS and not s.insecure_no_auth:
            raise ValueError("REKAMIND_AUTH=none hanya boleh di 127.0.0.1. Untuk server, pakai REKAMIND_AUTH=google.")
    else:
        raise ValueError(f"REKAMIND_AUTH='{s.auth}' tidak dikenal (google | local_token | none)")


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; "
                                "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"),
}


def create_app(settings: Settings | None = None, *, engines: Engines | None = None, http_client: httpx.AsyncClient | None = None) -> FastAPI:
    settings = settings or Settings()
    validate_auth_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.effective_database_url)
        await init_db(engine)
        app.state.sf = make_session_factory(engine)
        app.state.settings = settings
        own_http = http_client is None
        app.state.http = http_client or httpx.AsyncClient(follow_redirects=False)
        if settings.auth == "google":
            app.state.oidc = OidcClient(
                issuer=settings.oidc_issuer, client_id=settings.google_client_id, client_secret=settings.google_client_secret,
                redirect_uri=settings.public_url.rstrip("/") + "/auth/callback", http=app.state.http,
            )
        else:
            async with app.state.sf() as db:
                local = await auth_service.ensure_local_user(db)
                # Single-user modes: meetings from before accounts existed simply belong to this user.
                await db.execute(update(Meeting).where(Meeting.owner_id.is_(None)).values(owner_id=local.id))
                await db.commit()
                app.state.local_principal = auth_service.principal_of(local, "local")
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
        sweep = asyncio.create_task(trash.sweep_forever(app.state.sf, app.state.storage, settings.trash_days))
        yield
        sweep.cancel()
        if task:
            task.cancel()
        if own_http:
            await app.state.http.aclose()
        await engine.dispose()

    app = FastAPI(title="Rekamind", version=__version__, lifespan=lifespan)
    app.state.settings = settings  # available before startup too (the auth dependency reads it)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if settings.public_url.startswith("https://"):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    app.include_router(auth_routes.router)
    app.include_router(auth_routes.admin)

    async def session(request: Request):
        async with request.app.state.sf() as s:
            yield s

    Db = Annotated[AsyncSession, Depends(session)]
    User_ = Annotated[Principal, Depends(current_principal)]

    # ---- ownership: the one place that decides who may touch what -------------------------------
    def _mine(user: Principal):
        """Rows a super admin may see are everything; anyone else, only their own meetings."""
        return true() if user.is_superadmin else (Meeting.owner_id == user.id)

    def _listing(user: Principal, scope: str | None):
        if scope == "all":
            if not user.is_superadmin:
                raise HTTPException(403, "Hanya super admin yang boleh melihat semua rapat.")
            return true()
        return Meeting.owner_id == user.id  # even a super admin's default view is their own meetings

    async def _meeting(db: AsyncSession, meeting_id: str, user: Principal, *, deleted: bool = False) -> Meeting:
        q = select(Meeting).where(Meeting.id == meeting_id, _mine(user)).options(
            selectinload(Meeting.participants), selectinload(Meeting.segments), selectinload(Meeting.tasks), selectinload(Meeting.summary))
        if not deleted:
            q = q.where(Meeting.deleted_at.is_(None))
        m = (await db.execute(q)).scalar()
        if m is None:
            # 404, not 403: someone else's meeting must be indistinguishable from one that does not exist.
            raise HTTPException(404, "Rapat tidak ditemukan")
        return m

    async def _task(db: AsyncSession, task_id: str, user: Principal) -> Task:
        t = (await db.execute(select(Task).join(Meeting, Meeting.id == Task.meeting_id)
                              .where(Task.id == task_id, Meeting.deleted_at.is_(None), _mine(user)))).scalar()
        if t is None:
            raise HTTPException(404, "Task tidak ditemukan")
        return t

    async def _participant(db: AsyncSession, pid: str, user: Principal) -> Participant:
        p = (await db.execute(select(Participant).join(Meeting, Meeting.id == Participant.meeting_id)
                              .where(Participant.id == pid, Meeting.deleted_at.is_(None), _mine(user)))).scalar()
        if p is None:
            raise HTTPException(404, "Pembicara tidak ditemukan")
        return p

    # ---- public ---------------------------------------------------------------------------------
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    # ---- everything below needs a signed-in user --------------------------------------------------
    @app.get("/api/capabilities")
    async def capabilities(request: Request, _: User_):
        e: Engines | None = request.app.state.engines
        return {"processing_ready": e is not None, "engines": e.description if e else {}}

    @app.post("/api/meetings", status_code=201, response_model=MeetingSummaryOut)
    async def create_meeting(body: MeetingCreate, db: Db, user: User_):
        m = Meeting(title=body.title, language=body.language, local_user_name=body.local_user_name, owner_id=user.id,
                    started_at=body.started_at or datetime.now(UTC))
        db.add(m)
        await db.commit()
        await db.refresh(m, ["owner"])
        return m

    @app.get("/api/meetings", response_model=list[MeetingSummaryOut])
    async def list_meetings(db: Db, user: User_, limit: int = 50, offset: int = 0, q: str | None = None,
                            status: str | None = None, scope: str | None = None):
        query = select(Meeting).where(Meeting.deleted_at.is_(None), _listing(user, scope))
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
    async def get_meeting(meeting_id: str, db: Db, user: User_):
        return await _meeting(db, meeting_id, user)

    @app.patch("/api/meetings/{meeting_id}", response_model=MeetingSummaryOut)
    async def rename_meeting(meeting_id: str, body: MeetingPatch, db: Db, user: User_):
        m = await _meeting(db, meeting_id, user)
        m.title = body.title.strip()
        await db.commit()
        return m

    @app.post("/api/meetings/{meeting_id}/restore", response_model=MeetingSummaryOut)
    async def restore_meeting(meeting_id: str, db: Db, user: User_):
        m = await _meeting(db, meeting_id, user, deleted=True)
        m.deleted_at = None
        await db.commit()
        return m

    @app.get("/api/meetings/{meeting_id}/audio/{source}")
    async def get_audio(meeting_id: str, source: Literal["mic", "speaker"], request: Request, db: Db, user: User_):
        await _meeting(db, meeting_id, user)
        path = await request.app.state.storage.audio_path(meeting_id, source)
        if path is None:
            raise HTTPException(404, "Audio tidak tersedia")
        return FileResponse(path, media_type="audio/wav")  # Starlette serves Range requests, so seeking works

    @app.delete("/api/meetings/{meeting_id}", status_code=204)
    async def delete_meeting(meeting_id: str, request: Request, db: Db, user: User_, permanent: bool = False):
        m = await _meeting(db, meeting_id, user, deleted=permanent)
        if permanent:  # final: audio, transcript, tasks. Also works on a meeting already in the trash.
            try:
                await trash.purge_meeting(db, request.app.state.storage, m)
            except trash.Busy:
                raise HTTPException(409, "Rapat sedang diproses. Coba lagi setelah selesai.") from None
            return
        m.deleted_at = datetime.now(UTC)  # soft delete: undoable, and safe against sync resurrection
        await db.commit()

    @app.put("/api/meetings/{meeting_id}/audio/{source}", status_code=201)
    async def upload_audio(meeting_id: str, source: Literal["mic", "speaker"], request: Request, db: Db, user: User_):
        await _meeting(db, meeting_id, user)
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
    async def finish_meeting(meeting_id: str, db: Db, user: User_):
        m = await _meeting(db, meeting_id, user)
        if m.status != "recording":
            raise HTTPException(409, "Rapat tidak sedang direkam")
        m.status, m.ended_at = "recorded", datetime.now(UTC)
        await db.commit()
        return m

    @app.post("/api/meetings/{meeting_id}/process", status_code=202, response_model=JobOut)
    async def process_meeting(meeting_id: str, request: Request, db: Db, user: User_,
                              stage: Literal["all", "extract"] = "all"):
        if request.app.state.engines is None:
            raise HTTPException(503, "Mesin pemrosesan belum dikonfigurasi di backend ini")
        m = await _meeting(db, meeting_id, user)
        if m.status == "recording":
            raise HTTPException(409, "Selesaikan perekaman dulu sebelum memproses")
        if stage == "extract":  # only the summary and tasks again; needs a saved transcript
            has_transcript = (await db.execute(select(Segment.id).where(Segment.meeting_id == meeting_id).limit(1))).first()
            if not has_transcript:
                raise HTTPException(409, "Belum ada transkrip. Proses rapat dari awal.")
            return await jobs.enqueue(request.app.state.sf, meeting_id, kind="extract")
        return await jobs.enqueue(request.app.state.sf, meeting_id)

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    async def get_job(job_id: str, db: Db, user: User_):
        j = (await db.execute(select(Job).join(Meeting, Meeting.id == Job.meeting_id).where(Job.id == job_id, _mine(user)))).scalar()
        if j is None:
            raise HTTPException(404, "Job tidak ditemukan")
        return j

    @app.patch("/api/participants/{participant_id}", response_model=ParticipantOut)
    async def rename_participant(participant_id: str, body: ParticipantPatch, db: Db, user: User_):
        p = await _participant(db, participant_id, user)
        p.name = (body.name or "").strip() or None
        await db.commit()
        return p

    @app.get("/api/tasks", response_model=list[TaskWithMeeting])
    async def list_tasks(db: Db, user: User_, status: Literal["suggested", "confirmed", "rejected"] | None = None,
                         meeting_id: str | None = None, scope: str | None = None):
        q = (select(Task, Meeting.title).join(Meeting, Meeting.id == Task.meeting_id)
             .where(Meeting.deleted_at.is_(None), _listing(user, scope)).order_by(Task.created_at))
        if status:
            q = q.where(Task.status == status)
        if meeting_id:
            q = q.where(Task.meeting_id == meeting_id)
        return [TaskWithMeeting(**TaskOut.model_validate(t).model_dump(), meeting_title=title)
                for t, title in (await db.execute(q)).all()]

    @app.patch("/api/tasks/{task_id}", response_model=TaskOut)
    async def patch_task(task_id: str, body: TaskPatch, db: Db, user: User_):
        t = await _task(db, task_id, user)
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
        # Registered last so every /api and /auth route wins. Unknown paths fall back to index.html
        # so client-side routes survive a browser refresh.
        class SpaFiles(StaticFiles):
            async def get_response(self, path, scope):
                try:
                    return await super().get_response(path, scope)
                except Exception:
                    if path.startswith(("api/", "auth/")):
                        raise
                    return await super().get_response("index.html", scope)

        app.mount("/", SpaFiles(directory=web, html=True), name="web")
    return app
