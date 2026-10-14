import logging
import re
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from ..models import User
from . import service
from .deps import COOKIE, CurrentUser, SuperAdmin
from .oidc import InvalidToken, OidcError
from .ratelimit import RateLimiter
from .service import AccessDenied

log = logging.getLogger(__name__)
FLOW_COOKIE = "rk_flow"
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")

router = APIRouter()
admin = APIRouter(prefix="/api/admin")
_limiter = RateLimiter(limit=30, window_seconds=60)


def _safe_path(p: str | None) -> str:
    """Post-login destination: a local path only, so a crafted link cannot bounce users to another site."""
    return p if p and p.startswith("/") and not p.startswith("//") and "\\" not in p and "\n" not in p else "/"


def _page(status: int, title: str, message: str) -> HTMLResponse:
    body = (
        f'<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><body style=\"font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.5\">"
        f"<h1 style=\"font-size:1.25rem\">{escape(title)}</h1><p>{escape(message)}</p><p><a href=\"/\">Kembali ke Rekamind</a></p></body></html>"
    )
    return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _secure_cookie(request: Request) -> bool:
    return request.app.state.settings.public_url.startswith("https://")


# ---------------------------------------------------------------------------- public

@router.get("/auth/config")
async def auth_config(request: Request):
    s = request.app.state.settings
    return {"mode": s.auth, "login_url": "/auth/login" if s.auth == "google" else None}


@router.get("/auth/login")
async def login(request: Request, redirect: str | None = None, client: str | None = None, port: int | None = None, cc: str | None = None):
    _limiter.check(request)
    st = request.app.state
    if st.settings.auth != "google":
        raise HTTPException(404, "Login Google tidak aktif.")
    desktop = client == "desktop"
    if desktop and not (port and 1024 <= port <= 65535 and cc and _CHALLENGE.fullmatch(cc)):
        return _page(400, "Permintaan tidak valid", "Parameter login aplikasi desktop tidak lengkap.")
    async with st.sf() as db:
        flow, binding = await service.start_flow(
            db, redirect_to=_safe_path(redirect), desktop_port=port if desktop else None, desktop_challenge=cc if desktop else None,
        )
    try:
        url = await st.oidc.authorization_url(state=flow.state, nonce=flow.nonce, code_challenge=service.pkce_challenge(flow.code_verifier))
    except OidcError:
        log.exception("login: provider discovery failed")
        return _page(502, "Layanan login tidak tersedia", "Server tidak bisa menghubungi Google. Coba lagi nanti.")
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(FLOW_COOKIE, binding, max_age=600, httponly=True, samesite="lax", secure=_secure_cookie(request), path="/auth")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/auth/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    _limiter.check(request)
    st = request.app.state
    if st.settings.auth != "google":
        raise HTTPException(404, "Login Google tidak aktif.")
    denied = _page(403, "Tidak bisa masuk", "Login tidak dapat diselesaikan. Mulai lagi dari halaman utama. Jika terus berulang, hubungi administrator server.")
    if error or not code or not state:
        return denied
    try:
        async with st.sf() as db:
            flow = await service.consume_flow(db, state, request.cookies.get(FLOW_COOKIE))
        id_token = await st.oidc.exchange_code(code=code, code_verifier=flow.code_verifier)
        ident = await st.oidc.verify_id_token(id_token, expected_nonce=flow.nonce)
        async with st.sf() as db:
            user = await service.login_user(db, ident, st.settings)
            await db.commit()
            if flow.desktop_port:
                handoff = await service.create_login_code(db, user, flow.desktop_challenge or "")
                token = None
            else:
                token, _ = await service.create_session(db, user, "web", st.settings)
    except OidcError:
        log.exception("login: provider unreachable")
        return _page(502, "Layanan login tidak tersedia", "Server tidak bisa menghubungi Google. Coba lagi nanti.")
    except (AccessDenied, InvalidToken) as exc:
        log.warning("login refused: %s", getattr(exc, "reason", exc))
        # A person who authenticated fine but is not allowed deserves a clearer message than a failure.
        if isinstance(exc, AccessDenied) and exc.reason in ("not on the allow list", "account disabled"):
            return _page(403, "Akun Anda belum diizinkan", "Akun Google Anda berhasil diverifikasi, tetapi belum diizinkan memakai server ini. Minta administrator menambahkan Anda.")
        return denied

    if flow.desktop_port:
        resp = RedirectResponse(f"http://127.0.0.1:{flow.desktop_port}/callback?code={quote(handoff)}", status_code=302)
    else:
        resp = RedirectResponse(flow.redirect_to, status_code=302)
        days = st.settings.session_days
        resp.set_cookie(COOKIE, token, max_age=days * 86400, httponly=True, samesite="lax", secure=_secure_cookie(request), path="/")
    resp.delete_cookie(FLOW_COOKIE, path="/auth")
    resp.headers["Cache-Control"] = "no-store"
    return resp


class DesktopExchange(BaseModel):
    code: str = Field(min_length=20, max_length=200)
    verifier: str = Field(min_length=43, max_length=200)


@router.post("/auth/desktop/token")
async def desktop_token(body: DesktopExchange, request: Request):
    """The desktop app trades its one-time code (plus the PKCE verifier only it knows) for a token."""
    _limiter.check(request)
    st = request.app.state
    if st.settings.auth != "google":
        raise HTTPException(404, "Login Google tidak aktif.")
    async with st.sf() as db:
        try:
            user = await service.redeem_login_code(db, body.code, body.verifier)
        except AccessDenied as exc:
            log.warning("desktop exchange refused: %s", exc.reason)
            raise HTTPException(401, "Kode login tidak valid atau sudah kedaluwarsa.") from exc
        token, expires = await service.create_session(db, user, "desktop", st.settings)
    return JSONResponse(
        {"access_token": token, "token_type": "Bearer", "expires_at": expires.isoformat(),
         "user": {"id": user.id, "email": user.email, "name": user.name}},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, _: CurrentUser):
    st = request.app.state
    h = request.headers.get("authorization", "")
    token = h[7:].strip() if h.lower().startswith("bearer ") else request.cookies.get(COOKIE)
    if token and st.settings.auth == "google":
        async with st.sf() as db:
            await service.revoke_session(db, token)
    from fastapi import Response

    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/api/me")
async def me(request: Request, p: CurrentUser):
    return {"id": p.id, "email": p.email, "name": p.name, "picture": p.picture, "role": p.role, "auth_mode": request.app.state.settings.auth}


# ---------------------------------------------------------------------------- super admin

class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    disabled: bool
    invited: bool  # created by an admin, never signed in yet
    last_login_at: str | None
    meetings: int


class UserInvite(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(default="user", pattern="^(user|superadmin)$")


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|superadmin)$")
    disabled: bool | None = None


async def _active_superadmins(db) -> int:
    return (await db.execute(select(func.count()).select_from(User).where(User.role == "superadmin", User.disabled.is_(False)))).scalar() or 0


def _user_out(u: User, meetings: int) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, disabled=u.disabled, invited=u.sub is None,
                   last_login_at=u.last_login_at.isoformat() if u.last_login_at else None, meetings=meetings)


@admin.get("/users", response_model=list[UserOut])
async def list_users(request: Request, _: SuperAdmin):
    from ..models import Meeting

    async with request.app.state.sf() as db:
        counts = dict((await db.execute(select(Meeting.owner_id, func.count()).where(Meeting.deleted_at.is_(None)).group_by(Meeting.owner_id))).all())
        # NULL sub = an invitation: it must stay listed (SQL `NULL != x` is unknown, which would hide it).
        users = (await db.execute(select(User).where(or_(User.sub.is_(None), User.sub != service.LOCAL_SUB)).order_by(User.created_at))).scalars().all()
        return [_user_out(u, counts.get(u.id, 0)) for u in users]


@admin.post("/users", status_code=201, response_model=UserOut)
async def invite_user(body: UserInvite, request: Request, _: SuperAdmin):
    email = body.email.strip().lower()
    async with request.app.state.sf() as db:
        if (await db.execute(select(User).where(User.email == email))).scalar():
            raise HTTPException(409, "Email ini sudah terdaftar.")
        u = User(email=email, role=body.role)
        db.add(u)
        await db.commit()
        return _user_out(u, 0)


@admin.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: str, body: UserPatch, request: Request, actor: SuperAdmin):
    from ..models import Meeting

    async with request.app.state.sf() as db:
        u = await db.get(User, user_id)
        if u is None or u.sub == service.LOCAL_SUB:
            raise HTTPException(404, "Pengguna tidak ditemukan.")
        losing_admin = u.role == "superadmin" and not u.disabled and (body.role == "user" or body.disabled is True)
        if losing_admin and await _active_superadmins(db) <= 1:
            raise HTTPException(409, "Tidak bisa: ini super admin aktif terakhir.")
        if body.role is not None:
            u.role = body.role
        if body.disabled is not None:
            u.disabled = body.disabled
            if body.disabled:
                await service.revoke_user_sessions(db, u.id)  # off means off, immediately
        await db.commit()
        n = (await db.execute(select(func.count()).select_from(Meeting).where(Meeting.owner_id == u.id, Meeting.deleted_at.is_(None)))).scalar() or 0
        log.info("admin %s changed user %s: %s", actor.email, u.email, body.model_dump(exclude_none=True))
        return _user_out(u, n)
