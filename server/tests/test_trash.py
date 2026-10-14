from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from test_s3 import MID, _chunks, _storage, s3_endpoint  # noqa: F401  (fixture re-used)
from wavs import WAV

from rekamind_server import trash
from rekamind_server.models import Job, Meeting, Segment


async def _processed_meeting(client):
    m = (await client.post("/api/meetings", json={"title": "Akan dihapus"})).json()["id"]
    for src in ("mic", "speaker"):
        assert (await client.put(f"/api/meetings/{m}/audio/{src}", content=WAV)).status_code == 201
    await client.post(f"/api/meetings/{m}/finish")
    from rekamind_server.worker import Worker

    await client.post(f"/api/meetings/{m}/process")
    app = client.app
    assert await Worker(app.state.sf, app.state.storage, app.state.engines).run_once()
    return m


async def _count(client, model):
    async with client.app.state.sf() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar()


async def test_soft_delete_keeps_everything_and_permanent_delete_removes_everything(client, tmp_path):
    m = await _processed_meeting(client)
    audio = tmp_path / "recordings" / m
    assert audio.is_dir() and await _count(client, Segment) > 0

    assert (await client.delete(f"/api/meetings/{m}")).status_code == 204
    assert audio.is_dir(), "a soft delete must stay undoable"
    assert (await client.post(f"/api/meetings/{m}/restore")).status_code == 200

    assert (await client.delete(f"/api/meetings/{m}?permanent=true")).status_code == 204
    assert not audio.exists(), "audio must be gone for good"
    assert await _count(client, Meeting) == 0 and await _count(client, Segment) == 0 and await _count(client, Job) == 0
    assert (await client.get(f"/api/meetings/{m}")).status_code == 404


async def test_a_meeting_already_in_the_trash_can_be_removed_for_good(client, tmp_path):
    m = await _processed_meeting(client)
    await client.delete(f"/api/meetings/{m}")
    assert (await client.delete(f"/api/meetings/{m}?permanent=true")).status_code == 204
    assert not (tmp_path / "recordings" / m).exists()


async def test_permanent_delete_is_refused_while_the_meeting_is_being_processed(client):
    m = (await client.post("/api/meetings", json={"title": "x"})).json()["id"]
    await client.put(f"/api/meetings/{m}/audio/mic", content=WAV)
    await client.post(f"/api/meetings/{m}/finish")
    await client.post(f"/api/meetings/{m}/process")
    async with client.app.state.sf() as s:  # simulate the worker having claimed it
        (await s.execute(select(Job))).scalars().first().status = "running"
        await s.commit()
    r = await client.delete(f"/api/meetings/{m}?permanent=true")
    assert r.status_code == 409
    assert (await client.get(f"/api/meetings/{m}")).status_code == 200


async def test_expired_trash_is_purged_and_recent_trash_is_not(client, tmp_path):
    old, recent = await _processed_meeting(client), await _processed_meeting(client)
    await client.delete(f"/api/meetings/{old}")
    await client.delete(f"/api/meetings/{recent}")
    async with client.app.state.sf() as s:
        (await s.get(Meeting, old)).deleted_at = datetime.now(UTC) - timedelta(days=31)
        await s.commit()
    app = client.app
    assert await trash.purge_expired(app.state.sf, app.state.storage, 30) == 1
    assert not (tmp_path / "recordings" / old).exists() and (tmp_path / "recordings" / recent).exists()
    assert await trash.purge_expired(app.state.sf, app.state.storage, 0) == 0  # 0 = keep forever


async def test_object_store_audio_is_deleted_too(s3_endpoint, tmp_path):  # noqa: F811
    st = _storage(s3_endpoint, tmp_path, bucket="rk-trash")
    for src in ("mic", "speaker"):
        await st.save_audio(MID, src, _chunks(b"RIFFdata"))
    await st.delete_audio(MID)
    st.release_local(MID)
    assert await st.audio_path(MID, "mic") is None and await st.audio_path(MID, "speaker") is None
    await st.delete_audio(MID)  # deleting what is already gone is fine
