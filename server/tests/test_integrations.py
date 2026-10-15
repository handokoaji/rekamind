import hashlib
import hmac
import json
from urllib.parse import unquote

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_auth import BASE, ISSUER, MockIdp, Stack, make_processed_meeting, settings_for
from test_trash import _processed_meeting

from rekamind_server.api import create_app
from rekamind_server.config import Settings
from rekamind_server.engines.fake import fake_engines
from rekamind_server.models import Integration, Task

GH = {"kind": "github", "name": "Repo tim", "secret": "ghp_SECRETTOKEN",
      "config": {"repo": "kantor/proyek", "assignees": {"Budi": "budi-gh"}, "labels": ["rekamind", "rapat"]}}
GL = {"kind": "gitlab", "name": "GitLab tim", "secret": "glpat-SECRET",
      "config": {"project": "kantor/sub/proyek", "base_url": "https://git.kantor.id", "assignees": {"Budi": 77}}}


class Remote:
    """A pretend GitHub/GitLab/webhook that records every request it gets."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.next_number = 100
        self.fail: dict[str, httpx.Response] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        key = f"{req.method} {req.url.path}"
        for pattern, resp in self.fail.items():
            if pattern in key:
                return resp
        p = req.url.path
        if req.url.host == "api.github.com":
            if req.method == "GET":
                return httpx.Response(200, json={"full_name": "kantor/proyek", "has_issues": True, "permissions": {"push": True}})
            if req.method == "POST":
                self.next_number += 1
                return httpx.Response(201, json={"number": self.next_number, "html_url": f"https://github.com/kantor/proyek/issues/{self.next_number}"})
            return httpx.Response(200, json={"html_url": f"https://github.com/kantor/proyek/issues/{p.rsplit('/', 1)[1]}"})
        if req.url.host == "git.kantor.id":
            if req.method == "GET":
                return httpx.Response(200, json={"path_with_namespace": "kantor/sub/proyek", "issues_enabled": True})
            if p.endswith("/time_estimate"):
                return httpx.Response(200, json={})
            if req.method == "POST":
                self.next_number += 1
                return httpx.Response(201, json={"iid": self.next_number, "web_url": f"https://git.kantor.id/kantor/sub/proyek/-/issues/{self.next_number}"})
            return httpx.Response(200, json={"web_url": "https://git.kantor.id/x"})
        return httpx.Response(204)  # webhook receiver


@pytest.fixture
def remote(client):
    r = Remote()
    client.app.state.integration_transport = httpx.MockTransport(r)
    return r


async def _confirmed(client, n=2):
    m = await _processed_meeting(client)
    tasks = (await client.get(f"/api/meetings/{m}")).json()["tasks"]
    for t in tasks[:n]:
        assert (await client.patch(f"/api/tasks/{t['id']}", json={"status": "confirmed"})).status_code == 200
    return m, tasks[:n]


async def _add(client, spec):
    r = await client.post("/api/integrations", json=spec)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------------------ secrets
async def test_the_token_is_encrypted_at_rest_and_never_returned(client):
    i = await _add(client, GH)
    assert i["has_secret"] is True and "ghp_SECRETTOKEN" not in json.dumps(i)
    assert "ghp_SECRETTOKEN" not in json.dumps((await client.get("/api/integrations")).json())
    async with client.app.state.sf() as s:
        row = (await s.execute(select(Integration))).scalar()
        assert row.secret_enc and "ghp_SECRETTOKEN" not in row.secret_enc
        assert client.app.state.vault.open(row.secret_enc) == "ghp_SECRETTOKEN"
    assert (await client.get("/api/integrations/status")).json()["available"] is True


async def test_a_shared_server_without_a_key_refuses_to_store_tokens(tmp_path):
    idp = MockIdp()
    http = AsyncClient(transport=ASGITransport(app=idp.app), base_url=ISSUER)
    app = create_app(settings_for(tmp_path), engines=fake_engines(), http_client=http)
    async with app.router.lifespan_context(app):
        s = Stack(app, idp, http)
        alice = await s.user_browser("alice@kantor.id")
        st = (await alice.get("/api/integrations/status")).json()
        assert st["available"] is False and "REKAMIND_SECRET_KEY" in st["reason"]
        r = await alice.post("/api/integrations", json=GH, headers={"origin": BASE})
        assert r.status_code == 503 and "REKAMIND_SECRET_KEY" in r.json()["detail"]
        await s.close()
    await http.aclose()


# ------------------------------------------------------------------------------ validation
@pytest.mark.parametrize("spec,why", [
    ({**GH, "config": {"repo": "bukan-repo"}}, "repo"),
    ({**GH, "config": {"repo": "a/b", "base_url": "ftp://x"}}, "http"),
    ({**GH, "config": {"repo": "a/b", "base_url": "https://u:p@github.example"}}, "nama pengguna"),
    ({**GL, "config": {"project": "tanpa-slash-dan-bukan-angka"}}, "project"),
    ({"kind": "webhook", "name": "w", "config": {"url": "javascript:alert(1)"}}, "http"),
    ({"kind": "nope", "name": "w", "config": {}}, "kind"),
])
async def test_bad_destinations_and_configs_are_refused_with_a_reason(client, spec, why):
    r = await client.post("/api/integrations", json=spec)
    assert r.status_code == 422 and why.lower() in json.dumps(r.json()).lower(), r.text


async def test_on_a_shared_server_private_addresses_are_refused_and_loopback_names_too(tmp_path):
    s = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none",
                 integrations_allow_private=False, secret_key="x" * 40)
    app = create_app(s, engines=fake_engines())
    async with app.router.lifespan_context(app):
        # auth=none implies single user => private allowed; flip to shared behaviour for this check
        app.state.settings.auth = "none"
        from rekamind_server.integrations import IntegrationError, check_destination

        for url in ("http://example.com/hook", "https://127.0.0.1/hook", "https://localhost/hook", "https://169.254.169.254/latest",
                    "https://10.0.0.5/x", "https://[::1]/x"):
            with pytest.raises(IntegrationError):
                check_destination(url, allow_private=False)
        check_destination("http://127.0.0.1:9000/x", allow_private=True)


# ------------------------------------------------------------------------------ github
async def test_github_test_then_push_creates_issues_with_the_right_content(client, remote):
    i = await _add(client, GH)
    t = (await client.post(f"/api/integrations/{i['id']}/test")).json()
    assert t["ok"] is True and "kantor/proyek" in t["message"]
    m, tasks = await _confirmed(client)
    r = await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert [x["status"] for x in res] == ["created", "created"] and all(x["url"].startswith("https://github.com/kantor/proyek/issues/") for x in res)
    posts = [c for c in remote.calls if c.method == "POST"]
    assert len(posts) == 2 and all(p.url.path == "/repos/kantor/proyek/issues" for p in posts)
    first = posts[0]
    assert first.headers["authorization"] == "Bearer ghp_SECRETTOKEN" and first.headers["x-github-api-version"] == "2022-11-28"
    body = json.loads(first.content)
    assert body["title"] == "Siapkan draft kontrak" and body["labels"] == ["rekamind", "rapat"]
    assert body["assignees"] == ["budi-gh"], "the spoken name is mapped to a login"
    assert "Tenggat" in body["body"] and "Prioritas" in body["body"] and "Dibuat oleh Rekamind" in body["body"]
    links = (await client.get(f"/api/meetings/{m}/links")).json()
    assert len(links) == 2 and links[0]["state"] == "synced" and links[0]["integration"] == "Repo tim"


async def test_a_second_push_changes_nothing_unless_the_task_changed_and_then_updates_the_same_issue(client, remote):
    i = await _add(client, GH)
    m, tasks = await _confirmed(client, 1)
    await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})
    before = len(remote.calls)
    again = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert [x["status"] for x in again] == ["unchanged"] and len(remote.calls) == before, "no duplicate, no needless call"
    await client.patch(f"/api/tasks/{tasks[0]['id']}", json={"title": "Judul baru"})
    upd = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert [x["status"] for x in upd] == ["updated"]
    last = remote.calls[-1]
    assert last.method == "PATCH" and last.url.path == "/repos/kantor/proyek/issues/101" and json.loads(last.content)["title"] == "Judul baru"


async def test_an_issue_deleted_on_the_other_side_is_created_again(client, remote):
    i = await _add(client, GH)
    m, tasks = await _confirmed(client, 1)
    await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})
    await client.patch(f"/api/tasks/{tasks[0]['id']}", json={"title": "Diubah"})
    remote.fail["PATCH /repos/kantor/proyek/issues/101"] = httpx.Response(404, json={"message": "Not Found"})
    r = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert r[0]["status"] == "updated" and r[0]["url"].endswith("/102")


async def test_only_confirmed_tasks_can_be_sent_and_nothing_is_ever_sent_on_its_own(client, remote):
    i = await _add(client, GH)
    m = await _processed_meeting(client)
    tasks = (await client.get(f"/api/meetings/{m}")).json()["tasks"]
    r = await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})
    assert r.status_code == 422 and "dikonfirmasi" in r.json()["detail"] and not remote.calls
    r = await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"], "task_ids": [tasks[0]["id"]]})
    assert r.status_code == 422 and not remote.calls, "a suggested task cannot be pushed by naming it"
    await client.patch(f"/api/tasks/{tasks[0]['id']}", json={"status": "confirmed"})
    await client.patch(f"/api/tasks/{tasks[0]['id']}", json={"status": "rejected"})
    assert (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).status_code == 422
    assert not remote.calls, "confirming a task did not send it anywhere"


async def test_a_rejected_token_is_reported_per_task_with_advice_and_can_be_retried(client, remote):
    i = await _add(client, GH)
    m, _ = await _confirmed(client, 2)
    remote.fail["POST /repos/kantor/proyek/issues"] = httpx.Response(401, json={"message": "Bad credentials"})
    res = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert [x["status"] for x in res] == ["failed", "failed"] and "Token ditolak" in res[0]["error"] and "Bad credentials" in res[0]["error"]
    assert "ghp_SECRETTOKEN" not in json.dumps(res)
    assert {x["state"] for x in (await client.get(f"/api/meetings/{m}/links")).json()} == {"failed"}
    remote.fail.clear()
    ok = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert [x["status"] for x in ok] == ["created", "created"]


async def test_one_failing_task_does_not_stop_the_others(client, remote):
    i = await _add(client, GH)
    m, _ = await _confirmed(client, 2)
    n = {"c": 0}

    def flaky(req):
        if req.method == "POST":
            n["c"] += 1
            if n["c"] == 1:
                return httpx.Response(422, json={"message": "Validation Failed"})
        return remote(req)

    client.app.state.integration_transport = httpx.MockTransport(flaky)
    res = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert sorted(x["status"] for x in res) == ["created", "failed"]


# ------------------------------------------------------------------------------ gitlab
async def test_gitlab_issue_gets_labels_due_date_assignee_and_a_time_estimate(client, remote):
    i = await _add(client, GL)
    assert (await client.post(f"/api/integrations/{i['id']}/test")).json()["ok"] is True
    m, tasks = await _confirmed(client, 1)
    res = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert res[0]["status"] == "created" and "/-/issues/" in res[0]["url"]
    create = next(c for c in remote.calls if c.method == "POST" and c.url.path.endswith("/issues"))
    assert unquote(str(create.url.raw_path, "ascii")).startswith("/api/v4/projects/kantor/sub/proyek/issues")
    assert "kantor%2Fsub%2Fproyek" in str(create.url), "the project path is URL-encoded as one segment"
    assert create.headers["private-token"] == "glpat-SECRET" and "authorization" not in create.headers
    body = json.loads(create.content)
    assert body["labels"] == "rekamind" and body["assignee_ids"] == [77] and body["title"] == "Siapkan draft kontrak"
    assert "due_date" in body and body["due_date"][:2] == "20"
    est = [c for c in remote.calls if c.url.path.endswith("/time_estimate")]
    assert len(est) == 1 and est[0].url.params["duration"] == "2h"


# ------------------------------------------------------------------------------ webhook
async def test_webhook_is_signed_idempotent_and_never_follows_redirects(client, remote):
    i = await _add(client, {"kind": "webhook", "name": "Task manager kami", "secret": "whsec_abc", "config": {"url": "https://tasks.kantor.id/hook"}})
    assert (await client.post(f"/api/integrations/{i['id']}/test")).json()["ok"] is True
    m, tasks = await _confirmed(client, 1)
    res = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert res[0]["status"] == "created"
    req = remote.calls[-1]
    ts, sig = req.headers["x-rekamind-timestamp"], req.headers["x-rekamind-signature"]
    assert sig == "sha256=" + hmac.new(b"whsec_abc", ts.encode() + b"." + req.content, hashlib.sha256).hexdigest(), "receivers verify this"
    doc = json.loads(req.content)
    assert doc["schema"] == "rekamind.task/v1" and doc["event"] == "task.created" and doc["task"]["id"] == tasks[0]["id"]
    assert req.headers["idempotency-key"].startswith(tasks[0]["id"] + ":") and req.headers["x-rekamind-event"] == "task.created"
    # a redirect is a failure, not something to chase (it would carry the signature to another host)
    remote.fail["POST /hook"] = httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    await client.patch(f"/api/tasks/{tasks[0]['id']}", json={"title": "Ubah lagi"})
    res = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert res[0]["status"] == "failed" and "302" in res[0]["error"]
    assert all(c.url.host != "169.254.169.254" for c in remote.calls)


# ------------------------------------------------------------------------------ rate limits
async def test_a_429_with_retry_after_is_waited_out(client, remote, monkeypatch):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr("rekamind_server.integrations.asyncio.sleep", fake_sleep)
    i = await _add(client, GH)
    m, _ = await _confirmed(client, 1)
    sent = {"n": 0}

    def limited(req):
        if req.method == "POST":
            sent["n"] += 1
            if sent["n"] == 1:
                return httpx.Response(429, headers={"retry-after": "7"}, json={"message": "rate limit"})
        return remote(req)

    client.app.state.integration_transport = httpx.MockTransport(limited)
    res = (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).json()["results"]
    assert res[0]["status"] == "created" and waits == [7.0]


# ------------------------------------------------------------------------------ ownership
async def test_integrations_belong_to_their_owner_alone_not_even_to_a_super_admin(tmp_path):
    idp = MockIdp()
    http = AsyncClient(transport=ASGITransport(app=idp.app), base_url=ISSUER)
    app = create_app(settings_for(tmp_path, secret_key="k" * 40), engines=fake_engines(), http_client=http)
    app.state.integration_transport = httpx.MockTransport(Remote())
    async with app.router.lifespan_context(app):
        s = Stack(app, idp, http)
        alice = await s.user_browser("alice@kantor.id")
        bob = await s.user_browser("bob@kantor.id")
        boss = await s.user_browser("boss@kantor.id", sub="sub-boss")
        o = {"origin": BASE}
        i = (await alice.post("/api/integrations", json=GH, headers=o)).json()
        m, *_ = await make_processed_meeting(s, alice)
        tasks = (await alice.get(f"/api/meetings/{m}")).json()["tasks"]
        await alice.patch(f"/api/tasks/{tasks[0]['id']}", json={"status": "confirmed"}, headers=o)
        for who in (bob, boss):
            assert (await who.get("/api/integrations")).json() == []
            assert (await who.patch(f"/api/integrations/{i['id']}", json={"name": "x"}, headers=o)).status_code == 404
            assert (await who.delete(f"/api/integrations/{i['id']}", headers=o)).status_code == 404
            assert (await who.post(f"/api/integrations/{i['id']}/test", headers=o)).status_code == 404
        # Bob cannot push Alice's meeting, and the super admin cannot push with Alice's token
        assert (await bob.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]}, headers=o)).status_code == 404
        assert (await boss.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]}, headers=o)).status_code == 404
        assert (await bob.get(f"/api/meetings/{m}/links")).status_code == 404
        assert (await alice.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]}, headers=o)).status_code == 200
        await s.close()
    await http.aclose()


async def test_deleting_an_integration_removes_its_links_but_not_the_tasks_and_a_disabled_one_cannot_push(client, remote):
    i = await _add(client, GH)
    m, _ = await _confirmed(client, 1)
    await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})
    assert (await client.patch(f"/api/integrations/{i['id']}", json={"enabled": False})).json()["enabled"] is False
    assert (await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})).status_code == 409
    assert (await client.delete(f"/api/integrations/{i['id']}")).status_code == 204
    assert (await client.get(f"/api/meetings/{m}/links")).json() == []
    async with client.app.state.sf() as s:
        assert len((await s.execute(select(Task))).scalars().all()) >= 2


async def test_permanently_deleting_a_meeting_removes_its_links(client, remote):
    i = await _add(client, GH)
    m, _ = await _confirmed(client, 1)
    await client.post(f"/api/meetings/{m}/push", json={"integration_id": i["id"]})
    assert (await client.delete(f"/api/meetings/{m}?permanent=true")).status_code == 204
    assert (await client.get("/api/integrations")).json()[0]["id"] == i["id"]
