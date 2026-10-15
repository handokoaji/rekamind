"""Meetings are read in WIB by default. 'besok' said at 01:00 WIB is NOT the day after the UTC date."""
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from test_trash import _processed_meeting

from rekamind_server import tz as tzmod
from rekamind_server.api import create_app
from rekamind_server.config import Settings
from rekamind_server.engines.fake import fake_engines
from rekamind_server.models import Meeting


async def _set_start(client, m, when_utc):
    async with client.app.state.sf() as s:
        (await s.get(Meeting, m)).started_at = when_utc
        await s.commit()


async def test_a_deadline_said_after_midnight_wib_is_resolved_against_the_wib_date(client):
    # 18:00 UTC on the 14th is 01:00 WIB on the 15th (a Thursday). "besok" must be Friday the 16th.
    m = (await client.post("/api/meetings", json={"title": "Rapat dini hari", "started_at": "2026-10-14T18:00:00Z"})).json()["id"]
    from wavs import WAV

    from rekamind_server.worker import Worker
    for src in ("mic", "speaker"):
        await client.put(f"/api/meetings/{m}/audio/{src}", content=WAV)
    await client.post(f"/api/meetings/{m}/finish")
    await client.post(f"/api/meetings/{m}/process")
    a = client.app
    await Worker(a.state.sf, a.state.storage, a.state.engines).run_once()
    tasks = (await client.get(f"/api/meetings/{m}")).json()["tasks"]
    kontrak = next(t for t in tasks if t["title"] == "Siapkan draft kontrak")
    assert kontrak["deadline"] == "2026-10-16", f"resolved against the UTC date instead of the WIB date: {kontrak['deadline']}"


async def test_exports_show_the_clock_in_the_configured_zone_with_its_name(client):
    m = await _processed_meeting(client)
    await _set_start(client, m, datetime(2026, 10, 15, 2, 30, tzinfo=UTC))
    md = (await client.get(f"/api/meetings/{m}/export", params={"format": "md"})).text
    assert "15-10-2026 09:30 WIB" in md
    js = (await client.get(f"/api/meetings/{m}/export", params={"format": "json"})).json()
    assert js["meeting"]["timezone"] == "Asia/Jakarta" and js["meeting"]["started_at_local"] == "15-10-2026 09:30 WIB"
    assert (await client.get("/api/capabilities")).json()["timezone_label"] == "WIB"


async def test_another_zone_can_be_configured_and_an_unknown_one_is_refused_at_start(tmp_path):
    s = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none", timezone="Asia/Makassar")
    app = create_app(s, engines=fake_engines())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            caps = (await c.get("/api/capabilities")).json()
            assert caps["timezone"] == "Asia/Makassar" and caps["timezone_label"] == "WITA"
    with pytest.raises(ValueError, match="REKAMIND_TIMEZONE"):
        create_app(Settings(data_dir=tmp_path, auth="none", timezone="Mars/Olympus"))


def test_naive_timestamps_from_sqlite_are_taken_as_utc():
    z = tzmod.zone("Asia/Jakarta")
    assert tzmod.to_zone(datetime(2026, 10, 14, 18, 0), z).hour == 1  # not shifted by the machine's own zone
    assert tzmod.label(z) == "WIB" and tzmod.label(tzmod.zone("Asia/Jayapura")) == "WIT" and tzmod.label(tzmod.zone("UTC")) == "UTC"
