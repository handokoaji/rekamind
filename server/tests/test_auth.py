"""The security tests. They attack the server the way a hostile person or program would: forged and
replayed tokens, login links handed to someone else, other people's meetings, a stolen desktop code.
Where the browser would act, a real cookie jar does; the identity provider signs real RS256 tokens."""

import base64
import hashlib
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from mock_idp import ISSUER, Key, MockIdp
from sqlalchemy import select, update
from wavs import WAV

from rekamind_server.api import create_app, validate_auth_settings
from rekamind_server.auth import service
from rekamind_server.auth.oidc import InvalidToken, OidcClient, OidcError
from rekamind_server.config import Settings
from rekamind_server.engines.fake import fake_engines
from rekamind_server.models import AuthFlow, AuthSession, LoginCode, Meeting, User
from rekamind_server.worker import Worker

BASE = "http://127.0.0.1:8787"


class Stack:
    def __init__(self, app, idp, idp_http):
        self.app, self.idp, self.idp_http = app, idp, idp_http
        self._open: list[AsyncClient] = []

    def browser(self) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=self.app), base_url=BASE)
        self._open.append(c)
        return c

    async def start(self, browser, **params) -> httpx.Response:
        return await browser.get("/auth/login", params=params)

    async def at_idp(self, login_response) -> str:
        """The browser follows the redirect to the identity provider; returns where it sends it back."""
        r = await self.idp_http.get(login_response.headers["location"])
        return r.headers["location"]

    async def login(self, browser, *, redirect=None, **identity) -> httpx.Response:
        self.idp.identity = {**self.idp.identity, **identity}
        params = {"redirect": redirect} if redirect else {}
        r = await self.start(browser, **params)
        assert r.status_code == 302, r.text
        return await browser.get(await self.at_idp(r))

    async def user_browser(self, email, sub=None, **extra) -> AsyncClient:
        b = self.browser()
        r = await self.login(b, email=email, sub=sub or f"sub-{email}", name=email.split("@")[0], **extra)
        assert r.status_code == 302, f"login for {email} failed: {r.status_code} {r.text[:200]}"
        return b

    async def sql(self, stmt):
        async with self.app.state.sf() as db:
            res = await db.execute(stmt)
            await db.commit()
            return res

    async def close(self):
        for c in self._open:
            await c.aclose()


def settings_for(tmp_path, **over) -> Settings:
    base = dict(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="google",
                google_client_id="cid", google_client_secret="csecret", public_url=BASE, oidc_issuer=ISSUER,
                superadmins="boss@kantor.id", allowed_domains="kantor.id", signup="allowlist")
    return Settings(**{**base, **over})


@pytest.fixture
async def stack(tmp_path):
    idp = MockIdp()
    idp_http = AsyncClient(transport=ASGITransport(app=idp.app), base_url=ISSUER)
    app = create_app(settings_for(tmp_path), engines=fake_engines(), http_client=idp_http)
    async with app.router.lifespan_context(app):
        s = Stack(app, idp, idp_http)
        yield s
        await s.close()
    await idp_http.aclose()


def oidc(idp, http=None) -> OidcClient:
    return OidcClient(issuer=ISSUER, client_id="cid", client_secret="csecret", redirect_uri=idp.redirect_uri,
                      http=http or AsyncClient(transport=ASGITransport(app=idp.app), base_url=ISSUER))


# =================================================================== ID token verification

async def test_a_genuine_token_is_accepted_and_yields_the_identity():
    idp = MockIdp()
    ident = await oidc(idp).verify_id_token(idp.mint("n1"), expected_nonce="n1")
    assert (ident.sub, ident.email, ident.name) == ("sub-boss", "boss@kantor.id", "Boss")


async def test_signing_in_works_right_after_the_machine_booted(monkeypatch):
    # time.monotonic() counts from boot. The signing-key cache used 0.0 as "never fetched", which read as
    # "fetched a moment ago" for the first 5 minutes after boot, so a first login then failed with
    # "unknown signing key" (found when the sandbox restarted).
    import time as _time

    from rekamind_server.auth import oidc as oidc_mod

    real = _time.monotonic
    monkeypatch.setattr(oidc_mod.time, "monotonic", lambda: real() - real() + 30.0)  # 30 s after boot
    idp = MockIdp()
    ident = await oidc(idp).verify_id_token(idp.mint("n1"), expected_nonce="n1")
    assert ident.email == "boss@kantor.id"


@pytest.mark.parametrize("why,kwargs", [
    ("wrong audience (token meant for another app)", {"aud": "someone-elses-client"}),
    ("wrong issuer", {"iss": "https://evil.example"}),
    ("expired", {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}),
    ("issued in the future", {"iat": int(time.time()) + 3600, "exp": int(time.time()) + 7200}),
    ("no expiry at all", {"exp": None}),
    ("no subject", {"sub": None}),
    ("nonce from another login (replay)", {"nonce": "somebody-elses-nonce"}),
    ("no nonce", {"nonce": None}),
    ("email not verified", {"email_verified": False}),
    ("email_verified missing", {"email_verified": None}),
    ("email_verified as a string", {"email_verified": "true"}),
    ("no email", {"email": None}),
    ("several audiences without azp", {"aud": ["cid", "other"]}),
])
async def test_a_token_that_does_not_belong_to_this_login_is_refused(why, kwargs):
    idp = MockIdp()
    with pytest.raises(InvalidToken):
        await oidc(idp).verify_id_token(idp.mint("n1", **kwargs), expected_nonce="n1"), why


async def test_forged_signatures_and_algorithm_tricks_are_refused():
    idp = MockIdp()
    c = oidc(idp)
    forger = Key("k1")  # same key id, different private key: a forgery that "looks" right
    for label, tok in {
        "signed by someone else": idp.mint("n", key=forger),
        "alg=none (unsigned)": idp.mint("n", alg="none"),
        "HS256 with a guessed secret": idp.mint("n", alg="HS256"),
        "unknown key id": idp.mint("n", key=Key("never-published")),
        "garbage": "not.a.jwt",
        "empty": "",
    }.items():
        with pytest.raises(InvalidToken):
            await c.verify_id_token(tok, expected_nonce="n"), label


async def test_a_tampered_payload_fails_the_signature():
    idp = MockIdp()
    h, p, s = idp.mint("n").split(".")
    claims = jwt.decode(idp.mint("n"), options={"verify_signature": False})
    claims["email"] = "attacker@kantor.id"
    forged_payload = base64.urlsafe_b64encode(__import__("json").dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidToken):
        await oidc(idp).verify_id_token(f"{h}.{forged_payload}.{s}", expected_nonce="n")


async def test_key_rotation_is_picked_up_but_not_hammered(monkeypatch):
    idp = MockIdp()
    c = oidc(idp)
    await c.verify_id_token(idp.mint("n"), expected_nonce="n")
    new = Key("k2")
    idp.extra_keys.append(new)
    with pytest.raises(InvalidToken):  # unknown kid within the refresh floor: no refetch storm
        await c.verify_id_token(idp.mint("n", key=new), expected_nonce="n")
    monkeypatch.setattr("rekamind_server.auth.oidc._JWKS_MIN_REFRESH", 0)
    assert (await c.verify_id_token(idp.mint("n", key=new), expected_nonce="n")).sub == "sub-boss"


async def test_discovery_that_names_a_different_issuer_is_rejected():
    idp = MockIdp()
    http = AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "issuer": "https://evil.example", "authorization_endpoint": "x", "token_endpoint": "y", "jwks_uri": "z"})), base_url=ISSUER)
    with pytest.raises(OidcError):
        await oidc(idp, http).discovery()


# =================================================================== the web login flow

async def test_login_sends_a_correct_authorization_request_without_leaking_the_secret(stack):
    r = await stack.start(stack.browser())
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["response_type"] == ["code"] and q["client_id"] == ["cid"] and q["redirect_uri"] == [f"{BASE}/auth/callback"]
    assert q["code_challenge_method"] == ["S256"] and len(q["code_challenge"][0]) == 43
    assert {"state", "nonce"} <= q.keys() and q["scope"] == ["openid email profile"]
    assert "csecret" not in r.headers["location"], "the client secret must never travel through the browser"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/auth" in cookie


async def test_successful_login_sets_a_hardened_session_and_stores_only_a_hash(stack):
    b = stack.browser()
    r = await stack.login(b)
    assert r.status_code == 302 and r.headers["location"] == "/"
    sc = r.headers["set-cookie"].lower()
    assert "rk_session=rks_" in sc and "httponly" in sc and "samesite=lax" in sc
    me = (await b.get("/api/me")).json()
    assert (me["email"], me["role"], me["auth_mode"]) == ("boss@kantor.id", "superadmin", "google")
    raw = b.cookies.get("rk_session")
    rows = (await stack.sql(select(AuthSession.token_hash))).scalars().all()
    assert raw not in rows and hashlib.sha256(raw.encode()).hexdigest() in rows, "only the SHA-256 may be stored"
    assert "google-access-token-never-stored" not in str(rows)


async def test_a_login_link_cannot_be_replayed(stack):
    b = stack.browser()
    r = await stack.start(b)
    back = await stack.at_idp(r)
    assert (await b.get(back)).status_code == 302
    again = await b.get(back)  # same state and code a second time
    assert again.status_code == 403


async def test_a_login_started_by_an_attacker_cannot_be_completed_in_the_victims_browser(stack):
    """Login CSRF: the attacker starts a flow, then lures the victim onto the callback link."""
    attacker, victim = stack.browser(), stack.browser()
    stack.idp.identity = {**stack.idp.identity, "email": "boss@kantor.id"}
    back = await stack.at_idp(await stack.start(attacker))
    r = await victim.get(back)  # the victim's browser never started this login: no flow cookie
    assert r.status_code == 403
    assert (await victim.get("/api/me")).status_code == 401, "the victim must not end up logged in as the attacker"


async def test_an_expired_login_attempt_is_refused(stack):
    b = stack.browser()
    r = await stack.start(b)
    back = await stack.at_idp(r)
    await stack.sql(update(AuthFlow).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert (await b.get(back)).status_code == 403


async def test_the_provider_refusing_or_erroring_gives_a_generic_message_not_its_internals(stack):
    b = stack.browser()
    back = await stack.at_idp(await stack.start(b))
    stack.idp.token_status = 400
    r = await b.get(back)
    assert r.status_code == 403
    assert "secret detail" not in r.text and "invalid_grant" not in r.text
    r2 = await stack.browser().get("/auth/callback", params={"error": "access_denied", "state": "x"})
    assert r2.status_code == 403


async def test_an_unreachable_provider_is_a_502_page_not_a_stack_trace(tmp_path):
    def boom(request):
        raise httpx.ConnectError("down")

    http = AsyncClient(transport=httpx.MockTransport(boom))
    app = create_app(settings_for(tmp_path), http_client=http)
    async with app.router.lifespan_context(app):
        r = await AsyncClient(transport=ASGITransport(app=app), base_url=BASE).get("/auth/login")
    assert r.status_code == 502 and "Traceback" not in r.text and "ConnectError" not in r.text


@pytest.mark.parametrize("target,expected", [
    ("/rapat/abc?tab=task", "/rapat/abc?tab=task"),
    ("//evil.example/x", "/"),
    ("https://evil.example", "/"),
    ("/\\evil.example", "/"),
    ("javascript:alert(1)", "/"),
])
async def test_post_login_redirects_can_only_stay_on_this_site(stack, target, expected):
    r = await stack.login(stack.browser(), redirect=target)
    assert r.headers["location"] == expected


# =================================================================== who may sign in

async def test_allowlist_mode_lets_listed_domains_and_emails_in_and_turns_strangers_away(stack, tmp_path):
    ok = stack.browser()
    assert (await stack.login(ok, email="alice@kantor.id", sub="s-alice")).status_code == 302
    assert (await ok.get("/api/me")).json()["role"] == "user"

    stranger = stack.browser()
    r = await stack.login(stranger, email="stranger@gmail.com", sub="s-x")
    assert r.status_code == 403 and "belum diizinkan" in r.text
    assert (await stranger.get("/api/me")).status_code == 401
    assert not (await stack.sql(select(User).where(User.email == "stranger@gmail.com"))).scalars().all(), "no account is created for a refused person"


async def test_open_signup_admits_any_verified_google_account(tmp_path):
    idp = MockIdp()
    http = AsyncClient(transport=ASGITransport(app=idp.app), base_url=ISSUER)
    app = create_app(settings_for(tmp_path, signup="open", allowed_domains=""), http_client=http)
    async with app.router.lifespan_context(app):
        s = Stack(app, idp, http)
        b = await s.user_browser("anyone@gmail.com")
        assert (await b.get("/api/me")).status_code == 200
        await s.close()


async def test_a_super_admin_invitation_admits_someone_outside_the_allowlist_and_is_claimed_once(stack):
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    r = await boss.post("/api/admin/users", json={"email": "Guest@Elsewhere.org"}, headers={"origin": BASE})
    assert r.status_code == 201 and r.json()["invited"] is True and r.json()["email"] == "guest@elsewhere.org"

    guest = await stack.user_browser("guest@elsewhere.org", sub="sub-guest")
    assert (await guest.get("/api/me")).status_code == 200
    # The invitation is now bound to that Google account. Another account claiming the same address
    # (a recycled mailbox, a lookalike) is refused instead of merged.
    imposter = stack.browser()
    assert (await stack.login(imposter, email="guest@elsewhere.org", sub="sub-imposter")).status_code == 403
    assert (await imposter.get("/api/me")).status_code == 401


async def test_identity_is_the_google_sub_not_the_email(stack):
    first = await stack.user_browser("alice@kantor.id", sub="s-alice")
    mine = (await first.post("/api/meetings", json={"title": "Rahasia Alice"}, headers={"origin": BASE})).json()["id"]
    # Alice renames her address: same sub, new email -> same account, same meetings.
    again = stack.browser()
    assert (await stack.login(again, email="alice.baru@kantor.id", sub="s-alice")).status_code == 302
    assert (await again.get(f"/api/meetings/{mine}")).status_code == 200
    assert (await again.get("/api/me")).json()["email"] == "alice.baru@kantor.id"
    # Someone else later gets the OLD address (recycled): a different sub must not inherit anything.
    heir = stack.browser()
    await stack.login(heir, email="alice@kantor.id", sub="s-heir")
    assert (await heir.get(f"/api/meetings/{mine}")).status_code == 404


async def test_env_super_admin_is_promoted_on_login_even_if_the_account_existed_before(stack):
    b = stack.browser()
    await stack.login(b, email="boss@kantor.id", sub="sub-boss")
    assert (await b.get("/api/me")).json()["role"] == "superadmin"


async def test_a_disabled_account_cannot_log_in_and_existing_sessions_die_immediately(stack):
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    alice = await stack.user_browser("alice@kantor.id", sub="s-alice")
    uid = (await alice.get("/api/me")).json()["id"]
    r = await boss.patch(f"/api/admin/users/{uid}", json={"disabled": True}, headers={"origin": BASE})
    assert r.status_code == 200 and r.json()["disabled"] is True
    assert (await alice.get("/api/me")).status_code == 401, "off means off, immediately"
    again = stack.browser()
    assert (await stack.login(again, email="alice@kantor.id", sub="s-alice")).status_code == 403


async def test_re_enabling_an_account_does_not_resurrect_its_old_sessions(stack):
    """Disabling must really revoke: a cookie stolen before the account was disabled must stay dead
    even after an admin switches the account back on."""
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    alice = await stack.user_browser("alice@kantor.id", sub="s-alice")
    uid = (await alice.get("/api/me")).json()["id"]
    o = {"origin": BASE}
    await boss.patch(f"/api/admin/users/{uid}", json={"disabled": True}, headers=o)
    await boss.patch(f"/api/admin/users/{uid}", json={"disabled": False}, headers=o)
    assert (await alice.get("/api/me")).status_code == 401, "the old session was revoked, not just hidden"
    fresh = stack.browser()
    assert (await stack.login(fresh, email="alice@kantor.id", sub="s-alice")).status_code == 302, "a fresh login works"


# =================================================================== sessions, logout, CSRF

async def test_logout_revokes_the_session_server_side(stack):
    b = await stack.user_browser("alice@kantor.id")
    stolen = b.cookies.get("rk_session")
    assert (await b.post("/auth/logout", headers={"origin": BASE})).status_code == 204
    thief = stack.browser()
    thief.cookies.set("rk_session", stolen)
    assert (await thief.get("/api/me")).status_code == 401, "a copied cookie is worthless after logout"


async def test_expired_and_malformed_sessions_are_refused_and_sliding_expiry_extends(stack):
    b = await stack.user_browser("alice@kantor.id")
    assert (await b.get("/api/me")).status_code == 200
    await stack.sql(update(AuthSession).values(last_seen_at=datetime.now(UTC) - timedelta(hours=1), expires_at=datetime.now(UTC) + timedelta(hours=1)))
    assert (await b.get("/api/me")).status_code == 200
    row = (await stack.sql(select(AuthSession.expires_at))).scalar()
    row = row if row.tzinfo else row.replace(tzinfo=UTC)
    assert row > datetime.now(UTC) + timedelta(days=10), "activity pushes the expiry out"
    await stack.sql(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert (await b.get("/api/me")).status_code == 401
    for junk in ["", "rks_", "rks_" + "A" * 43, "Bearer", "x" * 500]:
        c = stack.browser()
        c.cookies.set("rk_session", junk)
        assert (await c.get("/api/me")).status_code == 401


async def test_state_changing_requests_with_a_cookie_must_come_from_our_own_origin(stack):
    b = await stack.user_browser("alice@kantor.id")
    body = {"title": "x"}
    assert (await b.post("/api/meetings", json=body)).status_code == 403, "no Origin header"
    assert (await b.post("/api/meetings", json=body, headers={"origin": "https://evil.example"})).status_code == 403
    assert (await b.post("/api/meetings", json=body, headers={"origin": BASE})).status_code == 201
    assert (await b.get("/api/meetings")).status_code == 200, "reads are not subject to the check"


# =================================================================== the desktop app's login

def pkce():
    verifier = base64.urlsafe_b64encode(hashlib.sha256(str(time.time_ns()).encode()).digest() * 2).rstrip(b"=").decode()[:64]
    return verifier, service.pkce_challenge(verifier)


async def desktop_code(stack, email="alice@kantor.id", port=51234):
    verifier, challenge = pkce()
    b = stack.browser()
    stack.idp.identity = {**stack.idp.identity, "email": email, "sub": f"s-{email}"}
    r = await stack.start(b, client="desktop", port=port, cc=challenge)
    assert r.status_code == 302, r.text
    final = await b.get(await stack.at_idp(r))
    assert final.status_code == 302
    loc = urlparse(final.headers["location"])
    assert (loc.scheme, loc.hostname, loc.port, loc.path) == ("http", "127.0.0.1", port, "/callback")
    return parse_qs(loc.query)["code"][0], verifier


async def test_desktop_login_hands_a_one_time_code_to_loopback_and_trades_it_for_a_bearer_token(stack):
    code, verifier = await desktop_code(stack)
    c = stack.browser()
    r = await c.post("/auth/desktop/token", json={"code": code, "verifier": verifier})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    tok = r.json()["access_token"]
    me = await c.get("/api/me", headers={"authorization": f"Bearer {tok}"})
    assert me.json()["email"] == "alice@kantor.id"
    # a bearer token is not ambient credentials: no Origin header needed for writes
    assert (await c.post("/api/meetings", json={"title": "dari desktop"}, headers={"authorization": f"Bearer {tok}"})).status_code == 201


async def test_a_stolen_desktop_code_is_useless_without_the_verifier_and_works_only_once(stack):
    code, verifier = await desktop_code(stack)
    c = stack.browser()
    wrong, _ = pkce()
    assert (await c.post("/auth/desktop/token", json={"code": code, "verifier": wrong + "x"})).status_code == 401
    assert (await c.post("/auth/desktop/token", json={"code": code, "verifier": verifier})).status_code == 200, "a wrong guess does not burn the real owner's code"
    assert (await c.post("/auth/desktop/token", json={"code": code, "verifier": verifier})).status_code == 401, "single use"


async def test_an_expired_desktop_code_is_refused(stack):
    code, verifier = await desktop_code(stack)
    await stack.sql(update(LoginCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert (await stack.browser().post("/auth/desktop/token", json={"code": code, "verifier": verifier})).status_code == 401


@pytest.mark.parametrize("params", [
    {"client": "desktop", "port": 80, "cc": "A" * 43},       # privileged port
    {"client": "desktop", "port": 70000, "cc": "A" * 43},
    {"client": "desktop", "port": 51234, "cc": "short"},
    {"client": "desktop", "port": 51234},                     # missing challenge
])
async def test_desktop_login_rejects_malformed_parameters(stack, params):
    r = await stack.start(stack.browser(), **params)
    assert r.status_code in (400, 422)


# =================================================================== who can see what

async def make_processed_meeting(stack, owner: AsyncClient, title="Rapat A"):
    m = (await owner.post("/api/meetings", json={"title": title}, headers={"origin": BASE})).json()["id"]
    for src in ("mic", "speaker"):
        assert (await owner.put(f"/api/meetings/{m}/audio/{src}", content=WAV, headers={"origin": BASE})).status_code == 201
    await owner.post(f"/api/meetings/{m}/finish", headers={"origin": BASE})
    job = (await owner.post(f"/api/meetings/{m}/process", headers={"origin": BASE})).json()["id"]
    a = stack.app
    await Worker(a.state.sf, a.state.storage, a.state.engines).run_once()
    d = (await owner.get(f"/api/meetings/{m}")).json()
    return m, job, d["tasks"][0]["id"], d["participants"][0]["id"]


async def test_a_user_can_only_ever_see_and_touch_their_own_meetings(stack):
    alice = await stack.user_browser("alice@kantor.id")
    bob = await stack.user_browser("bob@kantor.id")
    m, job, task, part = await make_processed_meeting(stack, alice)
    o = {"origin": BASE}

    attempts = [
        ("GET", f"/api/meetings/{m}", {}), ("PATCH", f"/api/meetings/{m}", {"json": {"title": "diretas"}}),
        ("DELETE", f"/api/meetings/{m}", {}), ("POST", f"/api/meetings/{m}/restore", {}),
        ("POST", f"/api/meetings/{m}/finish", {}), ("POST", f"/api/meetings/{m}/process", {}),
        ("GET", f"/api/meetings/{m}/audio/mic", {}), ("PUT", f"/api/meetings/{m}/audio/mic", {"content": WAV}),
        ("GET", f"/api/jobs/{job}", {}),
        ("PATCH", f"/api/tasks/{task}", {"json": {"status": "confirmed"}}),
        ("PATCH", f"/api/participants/{part}", {"json": {"name": "Diretas"}}),
    ]
    for method, path, kw in attempts:
        r = await bob.request(method, path, headers=o, **kw)
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}: someone else's data must look non-existent"
        assert r.json()["detail"] in {"Rapat tidak ditemukan", "Job tidak ditemukan", "Task tidak ditemukan", "Pembicara tidak ditemukan"}

    assert (await bob.get("/api/meetings")).json() == []
    assert (await bob.get("/api/tasks")).json() == []
    assert (await bob.get("/api/tasks", params={"meeting_id": m})).json() == []
    assert (await bob.get("/api/meetings", params={"scope": "all"})).status_code == 403
    mine = (await alice.get(f"/api/meetings/{m}")).json()
    assert mine["title"] == "Rapat A" and mine["status"] == "review", "nothing Bob attempted changed Alice's meeting"
    assert mine["tasks"][0]["status"] == "suggested" and mine["participants"][0]["name"] != "Diretas"


async def test_a_user_cannot_assign_a_task_to_a_participant_of_someone_elses_meeting(stack):
    alice = await stack.user_browser("alice@kantor.id")
    bob = await stack.user_browser("bob@kantor.id")
    _, _, _, alice_part = await make_processed_meeting(stack, alice, "Rapat A")
    _, _, bob_task, _ = await make_processed_meeting(stack, bob, "Rapat B")
    r = await bob.patch(f"/api/tasks/{bob_task}", json={"assignee_participant_id": alice_part}, headers={"origin": BASE})
    assert r.status_code == 422


async def test_a_super_admin_can_do_anything_but_their_default_view_is_their_own_meetings(stack):
    alice = await stack.user_browser("alice@kantor.id")
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    m, job, task, part = await make_processed_meeting(stack, alice)
    o = {"origin": BASE}

    assert (await boss.get("/api/meetings")).json() == [], "default list is only the admin's own"
    everyone = (await boss.get("/api/meetings", params={"scope": "all"})).json()
    assert [x["owner_email"] for x in everyone] == ["alice@kantor.id"]
    assert len((await boss.get("/api/tasks", params={"scope": "all"})).json()) == 2

    assert (await boss.get(f"/api/meetings/{m}")).status_code == 200
    assert (await boss.get(f"/api/meetings/{m}/audio/mic")).status_code == 200
    assert (await boss.get(f"/api/jobs/{job}")).status_code == 200
    assert (await boss.patch(f"/api/meetings/{m}", json={"title": "Diubah admin"}, headers=o)).json()["title"] == "Diubah admin"
    assert (await boss.patch(f"/api/tasks/{task}", json={"status": "confirmed"}, headers=o)).status_code == 200
    assert (await boss.patch(f"/api/participants/{part}", json={"name": "Nama"}, headers=o)).status_code == 200
    assert (await boss.post(f"/api/meetings/{m}/process", headers=o)).status_code == 202
    assert (await boss.delete(f"/api/meetings/{m}", headers=o)).status_code == 204
    assert (await boss.post(f"/api/meetings/{m}/restore", headers=o)).status_code == 200


async def test_meetings_from_before_accounts_existed_are_visible_to_super_admins_only(stack):
    alice = await stack.user_browser("alice@kantor.id")
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    await stack.sql(Meeting.__table__.insert().values(id="f" * 32, title="Warisan", status="done", language="id",
                                                       started_at=datetime.now(UTC), created_at=datetime.now(UTC)))
    assert (await alice.get(f"/api/meetings/{'f' * 32}")).status_code == 404
    assert (await boss.get(f"/api/meetings/{'f' * 32}")).status_code == 200


def iter_api_routes(routes):
    """Newer FastAPI wraps included routers in an opaque object; a naive loop over app.routes then
    silently skips every /auth and /api/admin route. Walk into them."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from iter_api_routes(r.original_router.routes)
        elif hasattr(r, "routes"):
            yield from iter_api_routes(r.routes)


async def test_every_route_requires_a_login_except_a_short_explicit_list(stack):
    """If someone adds an endpoint and forgets authentication, this fails, not production."""
    public = {("GET", "/api/health"), ("GET", "/auth/config"), ("GET", "/auth/login"), ("GET", "/auth/callback"), ("POST", "/auth/desktop/token")}
    c = stack.browser()
    checked, seen = 0, set()
    for route in iter_api_routes(stack.app.routes):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            seen.add((method, route.path))
            if (method, route.path) in public:
                continue
            path = re.sub(r"\{[^}]+\}", "x" * 32, route.path)
            r = await c.request(method, path, headers={"origin": BASE})
            assert r.status_code == 401, f"{method} {route.path} answered {r.status_code} without credentials"
            checked += 1
    assert checked >= 20, "the inventory walked too few routes to be meaningful"
    # The walk must really reach the nested routers, or the guarantee above is an illusion.
    assert {("GET", "/api/me"), ("POST", "/auth/logout"), ("GET", "/api/admin/users"), ("PATCH", "/api/admin/users/{user_id}")} <= seen
    assert public <= seen, "a public route disappeared from the inventory"


async def test_admin_endpoints_are_closed_to_ordinary_users(stack):
    alice = await stack.user_browser("alice@kantor.id")
    o = {"origin": BASE}
    assert (await alice.get("/api/admin/users")).status_code == 403
    assert (await alice.post("/api/admin/users", json={"email": "x@y.id"}, headers=o)).status_code == 403
    me = (await alice.get("/api/me")).json()["id"]
    assert (await alice.patch(f"/api/admin/users/{me}", json={"role": "superadmin"}, headers=o)).status_code == 403, "no self-promotion"


async def test_the_last_active_super_admin_cannot_be_removed(stack):
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    o = {"origin": BASE}
    me = (await boss.get("/api/me")).json()["id"]
    assert (await boss.patch(f"/api/admin/users/{me}", json={"role": "user"}, headers=o)).status_code == 409
    assert (await boss.patch(f"/api/admin/users/{me}", json={"disabled": True}, headers=o)).status_code == 409
    alice = await stack.user_browser("alice@kantor.id")
    aid = (await alice.get("/api/me")).json()["id"]
    assert (await boss.patch(f"/api/admin/users/{aid}", json={"role": "superadmin"}, headers=o)).json()["role"] == "superadmin"
    assert (await boss.patch(f"/api/admin/users/{me}", json={"role": "user"}, headers=o)).status_code == 200  # now there is another


async def test_admin_user_list_shows_counts_and_invitation_state(stack):
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    alice = await stack.user_browser("alice@kantor.id")
    await make_processed_meeting(stack, alice)
    await boss.post("/api/admin/users", json={"email": "baru@kantor.id"}, headers={"origin": BASE})
    users = {u["email"]: u for u in (await boss.get("/api/admin/users")).json()}
    assert users["alice@kantor.id"]["meetings"] == 1 and users["alice@kantor.id"]["invited"] is False
    assert users["baru@kantor.id"]["invited"] is True and users["baru@kantor.id"]["last_login_at"] is None


# =================================================================== the other modes and startup rules

async def test_local_token_mode_needs_the_secret_and_only_answers_on_loopback(tmp_path):
    token = "t" * 40
    app = create_app(Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="local_token", local_token=token))
    async with app.router.lifespan_context(app):
        def cl(host="127.0.0.1:8787"):
            return AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{host}", headers={"host": host})

        async with cl() as c:
            assert (await c.get("/api/meetings")).status_code == 401
            assert (await c.get("/api/meetings", headers={"authorization": "Bearer wrong"})).status_code == 401
            assert (await c.get("/api/meetings", headers={"authorization": f"Bearer {token}"})).status_code == 200
        async with cl("localhost:8787") as c:
            assert (await c.get("/api/meetings", headers={"authorization": f"Bearer {token}"})).status_code == 200
        for evil in ("evil.example", "evil.example:8787", "192.168.1.5:8787", "127.0.0.1.evil.example"):
            async with cl(evil) as c:  # DNS rebinding: right token, wrong Host -> still refused
                assert (await c.get("/api/meetings", headers={"authorization": f"Bearer {token}"})).status_code == 403, evil


async def test_no_auth_mode_also_refuses_a_foreign_host_header(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://rebind.evil.example") as c:
            assert (await c.get("/api/meetings")).status_code == 403


@pytest.mark.parametrize("over,needle", [
    (dict(google_client_id=""), "GOOGLE_CLIENT_ID"), (dict(google_client_secret=""), "CLIENT_SECRET"),
    (dict(public_url=""), "PUBLIC_URL"), (dict(superadmins=""), "SUPERADMINS"),
    (dict(public_url="http://kantor.id"), "https://"), (dict(signup="whatever"), "SIGNUP"),
    (dict(auth="local_token", local_token="short"), "LOCAL_TOKEN"),
    (dict(auth="none", host="0.0.0.0"), "127.0.0.1"), (dict(auth="magic"), "tidak dikenal"),
])
def test_a_misconfigured_server_refuses_to_start_and_says_what_to_set(tmp_path, over, needle):
    with pytest.raises(ValueError, match=needle):
        validate_auth_settings(settings_for(tmp_path, **over))


def test_no_auth_on_a_public_address_needs_an_explicit_insecure_flag(tmp_path):
    validate_auth_settings(settings_for(tmp_path, auth="none", host="0.0.0.0", insecure_no_auth=True))


async def test_security_headers_are_on_every_response_and_hsts_follows_https(stack):
    r = await stack.browser().get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers, "plain-http test URL: no HSTS"


async def test_login_endpoints_are_rate_limited(stack):
    b = stack.browser()
    codes = [(await b.get("/auth/login")).status_code for _ in range(35)]
    assert codes.count(429) >= 4 and codes[0] == 302
    assert (await b.get("/auth/login")).headers.get("retry-after") == "60"


async def test_permanent_delete_follows_ownership_and_a_super_admin_may_do_it(stack):
    alice = await stack.user_browser("alice@kantor.id")
    bob = await stack.user_browser("bob@kantor.id")
    boss = await stack.user_browser("boss@kantor.id", sub="sub-boss")
    o = {"origin": BASE}
    m, *_ = await make_processed_meeting(stack, alice, "Rapat rahasia")

    # a stranger can neither purge nor soft-delete, and learns nothing (404, same as "does not exist")
    assert (await bob.delete(f"/api/meetings/{m}?permanent=true", headers=o)).status_code == 404
    assert (await bob.delete(f"/api/meetings/{m}", headers=o)).status_code == 404
    assert (await alice.get(f"/api/meetings/{m}")).status_code == 200, "nothing happened to it"

    # not even after the owner has put it in the trash (the 'deleted' lookup must not widen access)
    assert (await alice.delete(f"/api/meetings/{m}", headers=o)).status_code == 204
    assert (await bob.delete(f"/api/meetings/{m}?permanent=true", headers=o)).status_code == 404
    assert (await bob.post(f"/api/meetings/{m}/restore", headers=o)).status_code == 404

    assert (await boss.delete(f"/api/meetings/{m}?permanent=true", headers=o)).status_code == 204
    assert (await alice.post(f"/api/meetings/{m}/restore", headers=o)).status_code == 404, "gone for good"
