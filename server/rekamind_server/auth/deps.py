"""Who is calling? Every /api route depends on `current_principal`; there is no way to forget it
for one route without the route-inventory test failing."""

import hmac
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request

from ..models import User
from .service import Principal, principal_of, resolve_session

COOKIE = "rk_session"
_SAFE = {"GET", "HEAD", "OPTIONS"}
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def host_is_loopback(host_header: str | None) -> bool:
    """Reject requests whose Host is not this machine. A web page that DNS-rebinds its own domain to
    127.0.0.1 can reach a local server from the user's browser, but it cannot make the browser send
    `Host: 127.0.0.1`: its Host stays its own domain."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8787
        host = host.split("]")[0] + "]"
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in _LOOPBACK


def allowed_origins(settings) -> set[str]:
    out = {o.strip().rstrip("/") for o in settings.cors_origins.split(",") if o.strip()}
    if settings.public_url:
        u = urlparse(settings.public_url)
        out.add(f"{u.scheme}://{u.netloc}")
    return out


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


async def current_principal(request: Request) -> Principal:
    st = request.app.state
    settings = st.settings

    if settings.auth in ("none", "local_token"):
        if not host_is_loopback(request.headers.get("host")):
            raise HTTPException(403, "Server lokal hanya melayani 127.0.0.1.")
        if settings.auth == "local_token":
            tok = _bearer(request) or ""
            if not settings.local_token or not hmac.compare_digest(tok.encode(), settings.local_token.encode()):
                raise HTTPException(401, "Token lokal tidak valid.", headers={"WWW-Authenticate": "Bearer"})
        return st.local_principal

    token, via = _bearer(request), "bearer"
    if not token:
        token, via = request.cookies.get(COOKIE), "cookie"
    if not token:
        raise HTTPException(401, "Silakan masuk.", headers={"WWW-Authenticate": "Bearer"})
    if via == "cookie" and request.method not in _SAFE:
        # SameSite=Lax already stops cross-site POSTs; this is the second, independent check.
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin not in allowed_origins(settings):
            raise HTTPException(403, "Asal permintaan tidak diizinkan.")
    async with st.sf() as db:
        user = await resolve_session(db, token, settings)
    if user is None:
        raise HTTPException(401, "Sesi berakhir. Silakan masuk lagi.", headers={"WWW-Authenticate": "Bearer"})
    return principal_of(user, via)


async def require_superadmin(p: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not p.is_superadmin:
        raise HTTPException(403, "Hanya super admin yang boleh melakukan ini.")
    return p


def user_row_to_principal(u: User) -> Principal:
    return principal_of(u, "local")


CurrentUser = Annotated[Principal, Depends(current_principal)]
SuperAdmin = Annotated[Principal, Depends(require_superadmin)]
