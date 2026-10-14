"""Accounts, sessions and login flows. No HTTP in here: everything is a function of the database
and the settings, so the security-relevant rules can be tested directly."""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import AuthFlow, AuthSession, LoginCode, User
from .oidc import Identity

TOKEN_PREFIX = "rks_"  # noqa: S105  (a label, not a credential)
FLOW_TTL = timedelta(minutes=10)
LOGIN_CODE_TTL = timedelta(minutes=2)
_TOUCH_EVERY = timedelta(minutes=10)
LOCAL_SUB = "local"
LOCAL_EMAIL = "local@localhost"


class AccessDenied(Exception):
    """Login refused. `reason` is for the server log; the user only ever sees a generic message."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    id: str
    email: str
    name: str | None
    picture: str | None
    role: str
    via: str  # "cookie" | "bearer" | "local"

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"


def now() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def principal_of(u: User, via: str) -> Principal:
    return Principal(id=u.id, email=u.email, name=u.name, picture=u.picture, role=u.role, via=via)


# ---------------------------------------------------------------------------- who may sign in

async def login_user(db: AsyncSession, ident: Identity, settings: Settings) -> User:
    """Apply the sign-in policy and return the (possibly new) user. Raises AccessDenied.

    Identity is Google's `sub`. The email is only a hint: if the email already belongs to a
    different Google account, that is refused rather than merged, so a recycled or re-assigned
    address can never inherit someone's meetings.
    """
    by_sub = (await db.execute(select(User).where(User.sub == ident.sub))).scalar()
    by_email = (await db.execute(select(User).where(User.email == ident.email))).scalar()
    is_super = ident.email in settings.superadmin_emails

    if by_sub is not None:
        user = by_sub
        if by_email is not None and by_email.id != user.id:
            pass  # the new address is taken by another row; keep ours as it is
        elif user.email != ident.email:
            user.email = ident.email
    elif by_email is not None:
        if by_email.sub is not None:
            raise AccessDenied("email belongs to a different Google account")
        user = by_email  # an invitation: this verified email claims it (trust on first use)
        user.sub = ident.sub
    else:
        domain = ident.email.rsplit("@", 1)[-1]
        allowed = (
            is_super
            or settings.signup == "open"
            or ident.email in settings.allowed_email_set
            or domain in settings.allowed_domain_set
        )
        if not allowed:
            raise AccessDenied("not on the allow list")
        user = User(sub=ident.sub, email=ident.email)
        db.add(user)

    if user.disabled:
        raise AccessDenied("account disabled")
    user.name, user.picture = ident.name or user.name, ident.picture or user.picture
    if is_super:
        user.role = "superadmin"
    user.last_login_at = now()
    await db.flush()
    return user


async def ensure_local_user(db: AsyncSession) -> User:
    """The one implicit user of `local_token` / `none` modes: this machine's owner."""
    u = (await db.execute(select(User).where(User.sub == LOCAL_SUB))).scalar()
    if u is None:
        u = User(sub=LOCAL_SUB, email=LOCAL_EMAIL, name="Pengguna lokal", role="superadmin")
        db.add(u)
        await db.commit()
    return u


# ---------------------------------------------------------------------------- sessions

async def create_session(db: AsyncSession, user: User, kind: str, settings: Settings) -> tuple[str, datetime]:
    days = settings.desktop_session_days if kind == "desktop" else settings.session_days
    token, expires = new_token(), now() + timedelta(days=days)
    db.add(AuthSession(user_id=user.id, token_hash=hash_token(token), kind=kind, expires_at=expires))
    await db.commit()
    return token, expires


async def resolve_session(db: AsyncSession, token: str, settings: Settings) -> User | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    t = now()
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None),
                   AuthSession.expires_at > t, User.disabled.is_(False))
        )
    ).first()
    if row is None:
        return None
    sess, user = row
    last = sess.last_seen_at if sess.last_seen_at.tzinfo else sess.last_seen_at.replace(tzinfo=UTC)
    if t - last > _TOUCH_EVERY:  # sliding expiry, written at most every few minutes
        days = settings.desktop_session_days if sess.kind == "desktop" else settings.session_days
        sess.last_seen_at, sess.expires_at = t, t + timedelta(days=days)
        await db.commit()
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(update(AuthSession).where(AuthSession.token_hash == hash_token(token)).values(revoked_at=now()).execution_options(synchronize_session=False))
    await db.commit()


async def revoke_user_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)).values(revoked_at=now()).execution_options(synchronize_session=False))


# ---------------------------------------------------------------------------- login flows

async def start_flow(db: AsyncSession, *, redirect_to: str, desktop_port: int | None, desktop_challenge: str | None) -> tuple[AuthFlow, str]:
    """Returns the stored flow and the secret browser-binding value to put in a cookie."""
    binding = secrets.token_urlsafe(32)
    flow = AuthFlow(
        state=secrets.token_urlsafe(32), nonce=secrets.token_urlsafe(32), code_verifier=secrets.token_urlsafe(64),
        binding_hash=hash_token(binding), redirect_to=redirect_to, desktop_port=desktop_port,
        desktop_challenge=desktop_challenge, expires_at=now() + FLOW_TTL,
    )
    db.add(flow)
    await db.commit()
    return flow, binding


async def consume_flow(db: AsyncSession, state: str, binding: str | None) -> AuthFlow:
    """Single use, enforced by the database: of two concurrent callbacks with the same state
    exactly one gets rowcount == 1."""
    flow = await db.get(AuthFlow, state)
    if flow is None:
        raise AccessDenied("unknown state")
    if not binding or not secrets.compare_digest(flow.binding_hash, hash_token(binding)):
        raise AccessDenied("login was not started in this browser")
    res = await db.execute(
        update(AuthFlow).where(AuthFlow.state == state, AuthFlow.used.is_(False), AuthFlow.expires_at > now()).values(used=True).execution_options(synchronize_session=False)
    )
    await db.commit()
    if res.rowcount != 1:
        raise AccessDenied("login link expired or already used")
    return flow


# ---------------------------------------------------------------------------- desktop hand-off

async def create_login_code(db: AsyncSession, user: User, challenge: str) -> str:
    code = secrets.token_urlsafe(32)
    db.add(LoginCode(code_hash=hash_token(code), user_id=user.id, challenge=challenge, expires_at=now() + LOGIN_CODE_TTL))
    await db.commit()
    return code


async def redeem_login_code(db: AsyncSession, code: str, verifier: str) -> User:
    row = await db.get(LoginCode, hash_token(code))
    # Same message for every failure: do not tell an attacker which part was wrong.
    if row is None or not secrets.compare_digest(row.challenge, pkce_challenge(verifier)):
        raise AccessDenied("bad login code or verifier")
    res = await db.execute(
        update(LoginCode).where(LoginCode.code_hash == row.code_hash, LoginCode.used.is_(False), LoginCode.expires_at > now()).values(used=True).execution_options(synchronize_session=False)
    )
    await db.commit()
    if res.rowcount != 1:
        raise AccessDenied("login code expired or already used")
    user = await db.get(User, row.user_id)
    if user is None or user.disabled:
        raise AccessDenied("account unavailable")
    return user
