"""Sending confirmed tasks to other systems: a signed webhook, GitHub issues, GitLab issues.

Rules that matter more than the HTTP details:
- only tasks a person CONFIRMED are ever sent, and only when a person asks (never automatically);
- a task is sent once: a second push updates the same issue (task_links), an unchanged task sends nothing;
- tokens are encrypted at rest and never leave the server again;
- the destination URL is user-supplied, so it is checked against private networks (SSRF) and redirects are refused.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, field_validator

from .export import clock, minutes_text
from .models import Meeting, Participant, Task
from .tz import DEFAULT as DEFAULT_TZ
from .tz import to_zone, zone

Kind = Literal["webhook", "github", "gitlab"]
TIMEOUT = 20.0
MAX_ATTEMPTS = 3
MAX_TASKS_PER_PUSH = 100
UA = "Rekamind"
PRIORITY = {"low": "rendah", "medium": "sedang", "high": "tinggi"}


class IntegrationError(Exception):
    """Something the user can act on (bad token, wrong repo, unreachable): shown as-is."""


# ----------------------------------------------------------------------------- destination checks
def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global or ip.is_multicast


def check_destination(url: str, *, allow_private: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise IntegrationError("Alamat harus diawali http:// atau https://")
    if parts.username or parts.password:
        raise IntegrationError("Alamat tidak boleh memuat nama pengguna/kata sandi; pakai kolom token.")
    if allow_private:
        return
    if parts.scheme != "https":
        raise IntegrationError("Server bersama hanya mengizinkan alamat https://")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise IntegrationError(f"Alamat {parts.hostname} tidak ditemukan (DNS)") from exc
    for info in infos:
        if _blocked(ipaddress.ip_address(info[4][0])):
            raise IntegrationError("Alamat mengarah ke jaringan privat/internal; tidak diizinkan di server bersama "
                                   "(administrator bisa mengizinkannya dengan REKAMIND_INTEGRATIONS_ALLOW_PRIVATE=true).")


# ----------------------------------------------------------------------------- config per kind
class WebhookConfig(BaseModel):
    url: str = Field(max_length=500)


_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GL_PROJECT = re.compile(r"^(\d+|[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+)$")


class _Tracker(BaseModel):
    base_url: str = Field(default="", max_length=300)
    labels: list[str] = Field(default_factory=lambda: ["rekamind"], max_length=10)
    assignees: dict[str, str | int] = Field(default_factory=dict, max_length=200)  # spoken name -> login / user id

    @field_validator("labels")
    @classmethod
    def _labels(cls, v: list[str]) -> list[str]:
        return [x.strip()[:50] for x in v if x.strip()]


class GithubConfig(_Tracker):
    repo: str

    @field_validator("repo")
    @classmethod
    def _repo(cls, v: str) -> str:
        if not _REPO.match(v):
            raise ValueError("repo harus berbentuk pemilik/nama, mis. kantor/proyek")
        return v


class GitlabConfig(_Tracker):
    project: str

    @field_validator("project")
    @classmethod
    def _project(cls, v: str) -> str:
        if not _GL_PROJECT.match(v):
            raise ValueError("project harus ID angka atau path grup/proyek")
        return v


CONFIGS = {"webhook": WebhookConfig, "github": GithubConfig, "gitlab": GitlabConfig}
DEFAULT_BASE = {"github": "https://api.github.com", "gitlab": "https://gitlab.com"}


def normalize_config(kind: str, config: dict) -> dict:
    cfg = CONFIGS[kind].model_validate(config).model_dump()
    if kind in DEFAULT_BASE:
        cfg["base_url"] = (cfg["base_url"] or DEFAULT_BASE[kind]).rstrip("/")
    return cfg


# ----------------------------------------------------------------------------- task payload
@dataclass(frozen=True)
class TaskPayload:
    id: str
    title: str
    description: str
    assignee: str | None
    deadline: date | None
    deadline_text: str | None
    approximate: bool
    estimate_minutes: int | None
    priority: str
    quote: str
    quote_at: str
    meeting_id: str
    meeting_title: str
    meeting_date: str

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True, default=str).encode()).hexdigest()

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "description": self.description, "assignee": self.assignee,
                "deadline": self.deadline.isoformat() if self.deadline else None, "deadline_text": self.deadline_text,
                "deadline_is_approximate": self.approximate, "estimate_minutes": self.estimate_minutes,
                "priority": self.priority, "evidence": {"quote": self.quote, "at": self.quote_at or None}}

    def markdown(self) -> str:
        meta = []
        if self.assignee:
            meta.append(f"**PIC:** {self.assignee}")
        if self.deadline:
            meta.append(f"**Tenggat:** {self.deadline.isoformat()}" + (" (perkiraan)" if self.approximate else ""))
        elif self.deadline_text:
            meta.append(f"**Tenggat:** {self.deadline_text}")
        if self.estimate_minutes:
            meta.append(f"**Estimasi:** {minutes_text(self.estimate_minutes)}")
        meta.append(f"**Prioritas:** {PRIORITY.get(self.priority, self.priority)}")
        out = [self.description.strip(), "", " · ".join(meta)] if self.description.strip() else [" · ".join(meta)]
        if self.quote:
            out += ["", f"> {self.quote}" + (f" ({self.quote_at})" if self.quote_at else "")]
        out += ["", f"_Dari rapat “{self.meeting_title}” ({self.meeting_date}). Dibuat oleh Rekamind setelah dikonfirmasi._"]
        return "\n".join(out).strip()


def payload_of(t: Task, m: Meeting, people: dict[str, Participant], tz: ZoneInfo | None = None) -> TaskPayload:
    p = people.get(t.assignee_participant_id or "")
    who = (p.name or p.label) if p else t.assignee_name
    return TaskPayload(
        id=t.id, title=t.title.strip()[:250], description=t.description or "", assignee=who, deadline=t.deadline,
        deadline_text=t.deadline_text, approximate=bool(t.deadline_approximate), estimate_minutes=t.estimate_minutes,
        priority=t.priority, quote=(t.evidence_quote or "").strip(), quote_at=clock(t.evidence_start_ms) if t.evidence_start_ms is not None else "",
        meeting_id=m.id, meeting_title=m.title, meeting_date=to_zone(m.started_at, tz or zone(DEFAULT_TZ)).date().isoformat() if m.started_at else "")


@dataclass(frozen=True)
class Ref:
    external_id: str
    url: str | None


# ----------------------------------------------------------------------------- HTTP with care
async def _send(http: httpx.AsyncClient, method: str, url: str, *, what: str, **kw) -> httpx.Response:
    """Retries rate limits and server errors (honouring Retry-After); everything else is the caller's to read."""
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = await http.request(method, url, **kw)
        except httpx.TransportError as exc:
            last = exc
            await asyncio.sleep(min(2 ** attempt, 8))
            continue
        if r.status_code in (429, 502, 503, 504) and attempt < MAX_ATTEMPTS - 1:
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = 2 ** attempt
            await asyncio.sleep(min(wait, 30))
            continue
        return r
    raise IntegrationError(f"{what}: tidak bisa menghubungi server ({type(last).__name__})")


def _explain(r: httpx.Response, what: str) -> IntegrationError:
    detail = ""
    try:
        j = r.json()
        detail = j.get("message") or j.get("error") or json.dumps(j)[:200]
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)[:200]
    except ValueError:
        detail = r.text[:200]
    hint = {401: " Token ditolak atau kedaluwarsa.", 403: " Token tidak punya izin (atau batas laju tercapai).",
            404: " Repo/proyek tidak ditemukan, atau token tidak bisa melihatnya."}.get(r.status_code, "")
    return IntegrationError(f"{what}: HTTP {r.status_code}.{hint} {detail}".strip())


# ----------------------------------------------------------------------------- adapters
class WebhookAdapter:
    def __init__(self, http: httpx.AsyncClient, cfg: dict, secret: str | None):
        self.http, self.url, self.secret = http, cfg["url"], secret

    def sign(self, body: bytes, ts: str) -> str:
        return "sha256=" + hmac.new((self.secret or "").encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

    async def _deliver(self, event: str, doc: dict, key: str) -> None:
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json", "User-Agent": UA, "X-Rekamind-Event": event,
                   "X-Rekamind-Delivery": uuid.uuid4().hex, "Idempotency-Key": key, "X-Rekamind-Timestamp": ts}
        if self.secret:
            headers["X-Rekamind-Signature"] = self.sign(body, ts)
        r = await _send(self.http, "POST", self.url, what="Webhook", content=body, headers=headers)
        if not 200 <= r.status_code < 300:
            raise _explain(r, "Webhook")

    def _doc(self, event: str, p: TaskPayload) -> dict:
        return {"schema": "rekamind.task/v1", "event": event, "meeting": {"id": p.meeting_id, "title": p.meeting_title, "date": p.meeting_date},
                "task": p.as_dict()}

    async def create(self, p: TaskPayload) -> Ref:
        await self._deliver("task.created", self._doc("task.created", p), f"{p.id}:{p.digest()}")
        return Ref(p.id, None)

    async def update(self, p: TaskPayload, ref: Ref) -> Ref:
        await self._deliver("task.updated", self._doc("task.updated", p), f"{p.id}:{p.digest()}")
        return ref

    async def test(self) -> str:
        doc = {"schema": "rekamind.task/v1", "event": "ping", "message": "Uji koneksi dari Rekamind"}
        await self._deliver("ping", doc, "ping:" + uuid.uuid4().hex)
        return "Webhook menjawab dengan sukses."


class GithubAdapter:
    def __init__(self, http: httpx.AsyncClient, cfg: dict, secret: str | None):
        if not secret:
            raise IntegrationError("Token GitHub belum diisi.")
        self.http, self.cfg = http, cfg
        self.base = f"{cfg['base_url']}/repos/{cfg['repo']}"
        self.headers = {"Authorization": f"Bearer {secret}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA}

    def _body(self, p: TaskPayload) -> dict:
        body: dict = {"title": p.title, "body": p.markdown(), "labels": self.cfg["labels"]}
        login = self.cfg["assignees"].get(p.assignee or "")
        if login:
            body["assignees"] = [str(login)]
        return body

    async def create(self, p: TaskPayload) -> Ref:
        r = await _send(self.http, "POST", f"{self.base}/issues", what="GitHub", headers=self.headers, json=self._body(p))
        if r.status_code != 201:
            raise _explain(r, "GitHub")
        j = r.json()
        return Ref(str(j["number"]), j.get("html_url"))

    async def update(self, p: TaskPayload, ref: Ref) -> Ref:
        r = await _send(self.http, "PATCH", f"{self.base}/issues/{ref.external_id}", what="GitHub", headers=self.headers, json=self._body(p))
        if r.status_code in (404, 410):
            return await self.create(p)  # the issue was deleted on the other side: send it again as a new one
        if r.status_code != 200:
            raise _explain(r, "GitHub")
        return Ref(ref.external_id, r.json().get("html_url") or ref.url)

    async def test(self) -> str:
        r = await _send(self.http, "GET", self.base, what="GitHub", headers=self.headers)
        if r.status_code != 200:
            raise _explain(r, "GitHub")
        j = r.json()
        if j.get("has_issues") is False:
            raise IntegrationError("Repositori ini menonaktifkan fitur Issues.")
        perms = j.get("permissions") or {}
        extra = "" if perms.get("push") or perms.get("triage") or perms.get("admin") else " Peringatan: token mungkin tidak boleh membuat issue."
        return f"Terhubung ke {j.get('full_name', self.cfg['repo'])}.{extra}"


class GitlabAdapter:
    def __init__(self, http: httpx.AsyncClient, cfg: dict, secret: str | None):
        if not secret:
            raise IntegrationError("Token GitLab belum diisi.")
        self.http, self.cfg = http, cfg
        self.base = f"{cfg['base_url']}/api/v4/projects/{quote(str(cfg['project']), safe='')}"
        self.headers = {"PRIVATE-TOKEN": secret, "User-Agent": UA}

    def _body(self, p: TaskPayload) -> dict:
        body: dict = {"title": p.title, "description": p.markdown(), "labels": ",".join(self.cfg["labels"])}
        if p.deadline:
            body["due_date"] = p.deadline.isoformat()
        uid = self.cfg["assignees"].get(p.assignee or "")
        if uid not in (None, ""):
            body["assignee_ids"] = [int(uid)]
        return body

    async def _estimate(self, iid: str, p: TaskPayload) -> None:
        if not p.estimate_minutes:
            return
        h, m = divmod(p.estimate_minutes, 60)
        dur = (f"{h}h" if h else "") + (f"{m}m" if m else "")
        # best effort: an estimate the project does not accept must not fail the issue that was just created
        await _send(self.http, "POST", f"{self.base}/issues/{iid}/time_estimate", what="GitLab", headers=self.headers, params={"duration": dur})

    async def create(self, p: TaskPayload) -> Ref:
        r = await _send(self.http, "POST", f"{self.base}/issues", what="GitLab", headers=self.headers, json=self._body(p))
        if r.status_code != 201:
            raise _explain(r, "GitLab")
        j = r.json()
        await self._estimate(str(j["iid"]), p)
        return Ref(str(j["iid"]), j.get("web_url"))

    async def update(self, p: TaskPayload, ref: Ref) -> Ref:
        r = await _send(self.http, "PUT", f"{self.base}/issues/{ref.external_id}", what="GitLab", headers=self.headers, json=self._body(p))
        if r.status_code == 404:
            return await self.create(p)
        if r.status_code != 200:
            raise _explain(r, "GitLab")
        await self._estimate(ref.external_id, p)
        return Ref(ref.external_id, r.json().get("web_url") or ref.url)

    async def test(self) -> str:
        r = await _send(self.http, "GET", self.base, what="GitLab", headers=self.headers)
        if r.status_code != 200:
            raise _explain(r, "GitLab")
        j = r.json()
        if j.get("issues_enabled") is False:
            raise IntegrationError("Proyek ini menonaktifkan fitur Issues.")
        return f"Terhubung ke {j.get('path_with_namespace', self.cfg['project'])}."


ADAPTERS = {"webhook": WebhookAdapter, "github": GithubAdapter, "gitlab": GitlabAdapter}


def make_http(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    # follow_redirects=False: a destination must not bounce the request (and the token) to another host
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, transport=transport)
