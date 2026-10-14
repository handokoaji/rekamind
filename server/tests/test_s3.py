import socket

import pytest
from httpx import ASGITransport, AsyncClient
from wavs import WAV

from rekamind_server.api import create_app
from rekamind_server.config import Settings
from rekamind_server.engines.fake import fake_engines
from rekamind_server.storage import S3Storage
from rekamind_server.worker import Worker

MID = "a" * 32


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def s3_endpoint():
    """A real S3-protocol server listening on a socket (moto), not mocked boto calls."""
    from moto.server import ThreadedMotoServer

    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


def _storage(endpoint, tmp_path, bucket="rk-test", prefix=""):
    s = S3Storage(endpoint_url=endpoint, bucket=bucket, access_key="k", secret_key="s", cache_dir=tmp_path / "cache", prefix=prefix)
    s.ensure_bucket()
    return s


async def _chunks(*parts: bytes):
    for p in parts:
        yield p


async def test_roundtrip_through_object_store_not_just_the_cache(s3_endpoint, tmp_path):
    st = _storage(s3_endpoint, tmp_path)
    assert await st.save_audio(MID, "mic", _chunks(b"RIFF", b"data" * 1000)) == 4004
    st.release_local(MID)  # drop the cache: the next read MUST come from the bucket
    p = await st.audio_path(MID, "mic")
    assert p is not None and p.read_bytes() == b"RIFF" + b"data" * 1000


async def test_missing_object_returns_none_and_leaves_no_partial_file(s3_endpoint, tmp_path):
    st = _storage(s3_endpoint, tmp_path)
    assert await st.audio_path("b" * 32, "speaker") is None
    assert list((tmp_path / "cache").rglob("*.part")) == []


async def test_empty_upload_is_not_stored(s3_endpoint, tmp_path):
    st = _storage(s3_endpoint, tmp_path)
    assert await st.save_audio("c" * 32, "mic", _chunks()) == 0
    st.release_local("c" * 32)
    assert await st.audio_path("c" * 32, "mic") is None


async def test_prefix_isolates_tenants_sharing_a_bucket(s3_endpoint, tmp_path):
    a = _storage(s3_endpoint, tmp_path / "a", prefix="team-a")
    b = _storage(s3_endpoint, tmp_path / "b", prefix="team-b")
    await a.save_audio(MID, "mic", _chunks(b"A"))
    a.release_local(MID)
    assert await b.audio_path(MID, "mic") is None


@pytest.mark.parametrize("bad", ["../../etc", "A" * 32, "a" * 31, "a/b"])
async def test_hostile_ids_never_reach_the_bucket_or_filesystem(s3_endpoint, tmp_path, bad):
    st = _storage(s3_endpoint, tmp_path)
    with pytest.raises(ValueError):
        await st.save_audio(bad, "mic", _chunks(b"x"))
    with pytest.raises(ValueError):
        st.release_local(bad)


async def test_whole_pipeline_runs_on_s3_and_cleans_its_cache(s3_endpoint, tmp_path):
    settings = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none",
                        storage="s3", s3_endpoint_url=s3_endpoint, s3_bucket="rk-e2e", s3_access_key="k", s3_secret_key="s")
    app = create_app(settings, engines=fake_engines())
    async with app.router.lifespan_context(app):  # also proves the bucket is auto-created
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            m = (await c.post("/api/meetings", json={"title": "S3"})).json()
            for src in ("mic", "speaker"):
                assert (await c.put(f"/api/meetings/{m['id']}/audio/{src}", content=WAV)).status_code == 201
            await c.post(f"/api/meetings/{m['id']}/finish")
            await c.post(f"/api/meetings/{m['id']}/process")
            st = app.state
            app.state.storage.release_local(m["id"])  # force the worker to download from S3
            await Worker(st.sf, st.storage, st.engines).run_once()
            d = (await c.get(f"/api/meetings/{m['id']}")).json()
            assert d["status"] == "review" and len(d["segments"]) == 4
            assert not (tmp_path / "cache" / m["id"]).exists()  # cache dropped after the job


def test_s3_requires_credentials():
    from rekamind_server.api import build_storage

    with pytest.raises(ValueError, match="ACCESS_KEY"):
        build_storage(Settings(storage="s3"))
    with pytest.raises(ValueError, match="tidak dikenal"):
        build_storage(Settings(storage="ftp"))
