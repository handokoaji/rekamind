import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.storage.models import Speaker, Summary, TranscriptSegment, Meeting
from app.sync import minio_client


def test_client_strips_scheme_from_endpoint_and_infers_secure():
    class Settings:
        minio_endpoint = "http://10.55.11.194:7001"
        minio_access_key = "a"
        minio_secret_key = "b"

    # Previously raised ValueError("path in endpoint is not allowed") --
    # minio-py's `endpoint` must be host:port only, scheme goes in `secure`.
    client = minio_client._client(Settings())

    assert client._base_url.is_https is False
    assert client._base_url.host == "10.55.11.194:7001"


def test_build_manifest_includes_meeting_fields_and_final_segments_only():
    meeting = Meeting(
        id=1, title="Rapat Rilis", device_id="dev1", device_label="Laptop Budi",
        status="completed",
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc),
    )
    speakers_by_id = {5: Speaker(id=5, meeting_id=1, label="Speaker 1")}
    segments = [
        TranscriptSegment(meeting_id=1, speaker_id=None, source="mic",
                           start_ms=0, end_ms=900, text="Halo", is_final=True),
        TranscriptSegment(meeting_id=1, speaker_id=5, source="speaker",
                           start_ms=900, end_ms=1500, text="Draft", is_final=False),
    ]

    manifest = minio_client.build_manifest(meeting, segments, speakers_by_id, summary=None)

    assert manifest["title"] == "Rapat Rilis"
    assert manifest["device_id"] == "dev1"
    assert manifest["device_label"] == "Laptop Budi"
    assert manifest["status"] == "completed"
    assert manifest["start_time"] == "2026-07-31T09:00:00+00:00"
    assert len(manifest["segments"]) == 1  # the draft (is_final=False) is excluded
    assert manifest["segments"][0] == {
        "speaker_label": "Anda", "source": "mic", "start_ms": 0, "end_ms": 900, "text": "Halo",
    }
    assert manifest["summary"] is None


def test_build_manifest_resolves_speaker_labels_for_non_mic_segments():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="recorded")
    speakers_by_id = {5: Speaker(id=5, meeting_id=1, label="Speaker 1")}
    segments = [
        TranscriptSegment(meeting_id=1, speaker_id=5, source="speaker",
                           start_ms=0, end_ms=500, text="Mari mulai", is_final=True),
    ]

    manifest = minio_client.build_manifest(meeting, segments, speakers_by_id, summary=None)

    assert manifest["segments"][0]["speaker_label"] == "Speaker 1"


def test_build_manifest_includes_summary_when_present():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="completed")
    summary = Summary(
        meeting_id=1, mom_json='{"x": 1}', docx_path="/some/path/mom.docx",
        groq_model="openai/gpt-oss-120b", status="ready",
    )

    manifest = minio_client.build_manifest(meeting, [], {}, summary=summary)

    assert manifest["summary"] == {
        "mom_json": '{"x": 1}', "has_docx": True,
        "groq_model": "openai/gpt-oss-120b", "status": "ready",
    }


def test_build_manifest_summary_has_docx_false_when_docx_path_is_none():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="completed")
    summary = Summary(meeting_id=1, mom_json="{}", docx_path=None, groq_model="m", status="ready")

    manifest = minio_client.build_manifest(meeting, [], {}, summary=summary)

    assert manifest["summary"]["has_docx"] is False


def test_manifest_object_prefix_shape():
    assert minio_client.manifest_object_prefix("dev1", "uuid123") == "dev1/uuid123"


import asyncio
import sys
from types import ModuleType
from unittest.mock import MagicMock

from app.storage.db import init_db, make_engine, make_session_factory
from app.storage import repository as repo


class FakeSettings:
    def __init__(self, device_id="dev1"):
        self.device_id = device_id
        self.minio_endpoint = "play.min.io"
        self.minio_access_key = "ak"
        self.minio_secret_key = "sk"
        self.minio_bucket = "meetings"
        self.minio_is_configured = True


def _fake_minio_module():
    module = ModuleType("minio")
    module.Minio = MagicMock()
    return module


def _make_db():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    return make_session_factory(engine)


def test_push_uploads_manifest_and_files_for_own_meetings_only(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    session_factory = _make_db()

    async def _seed():
        async with session_factory() as session:
            own = await repo.create_meeting(
                session, "Rapat Saya", None, recording_dir=str(tmp_path / "own"),
                device_id="dev1", device_label="Laptop Budi",
            )
            other = await repo.create_meeting(
                session, "Rapat Lain", None, recording_dir=str(tmp_path / "other"),
                device_id="dev2", device_label="Laptop Lain",
            )
            await session.commit()
            return own.id, other.id

    own_id, other_id = asyncio.run(_seed())
    (tmp_path / "own").mkdir()
    (tmp_path / "own" / "mic.wav").write_bytes(b"fake")

    result = minio_client.push(session_factory, FakeSettings())

    assert result["manifests"] == 1  # only the meeting owned by dev1
    fake_client.put_object.assert_called()  # manifest.json uploaded
    fake_client.fput_object.assert_called()  # mic.wav uploaded
    uploaded_keys = [c.args[1] for c in fake_client.put_object.call_args_list]
    assert any(k.startswith("dev1/") for k in uploaded_keys)
    assert not any(k.startswith("dev2/") for k in uploaded_keys)


def test_push_does_not_mark_synced_when_no_files_exist_yet(monkeypatch, tmp_path):
    """Regression test: synced_at was set unconditionally after the upload
    loop even when zero files existed on disk yet (e.g. syncing a meeting
    right after it's created, before any WAV has been written). That
    permanently marked the meeting "synced" so its files would never be
    uploaded on any later sync, since push() only looks at a meeting's
    files at all when synced_at is still None."""
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    session_factory = _make_db()

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Rapat Baru", None, recording_dir=str(tmp_path / "own"),
                device_id="dev1", device_label="Laptop Budi",
            )
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())
    # Deliberately no tmp_path/"own" directory at all -- recording hasn't
    # started writing files yet, matches the real timing this bug hits.

    result = minio_client.push(session_factory, FakeSettings())

    assert result["uploaded"] == 0
    fake_client.fput_object.assert_not_called()

    async def _get_synced_at():
        async with session_factory() as session:
            m = await session.get(Meeting, meeting_id)
            return m.synced_at

    assert asyncio.run(_get_synced_at()) is None


def test_push_skips_re_uploading_files_when_already_synced(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    session_factory = _make_db()

    async def _seed_and_mark_synced():
        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Rapat", None, recording_dir=str(tmp_path / "own"),
                device_id="dev1", device_label="Laptop Budi",
            )
            await session.commit()
            meeting.synced_at = datetime.now(timezone.utc)
            await session.commit()

    asyncio.run(_seed_and_mark_synced())
    (tmp_path / "own").mkdir()
    (tmp_path / "own" / "mic.wav").write_bytes(b"fake")

    minio_client.push(session_factory, FakeSettings())

    fake_client.put_object.assert_called()  # manifest still re-uploaded
    fake_client.fput_object.assert_not_called()  # but not the WAV, already synced


def _fake_object(name):
    obj = MagicMock()
    obj.object_name = name
    return obj


def _fake_manifest_response(manifest: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(manifest).encode("utf-8")
    return resp


def test_pull_creates_local_meeting_from_remote_manifest(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    remote_manifest = {
        "title": "Rapat Remote", "scheduled_time": None, "start_time": None, "end_time": None,
        "status": "completed", "device_id": "dev2", "device_label": "Laptop Lain",
        "segments": [
            {"speaker_label": "Anda", "source": "mic", "start_ms": 0, "end_ms": 500, "text": "Halo"},
            {"speaker_label": "Speaker 1", "source": "speaker", "start_ms": 500, "end_ms": 900, "text": "Mari mulai"},
        ],
        "summary": {"mom_json": "{}", "has_docx": True, "groq_model": "m", "status": "ready"},
    }
    fake_client.list_objects.return_value = [_fake_object("dev2/uuid123/manifest.json")]
    fake_client.get_object.return_value = _fake_manifest_response(remote_manifest)

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 1

    async def _get():
        async with session_factory() as session:
            r = await session.execute(select(Meeting))
            return r.scalars().all()

    meetings = asyncio.run(_get())
    assert len(meetings) == 1
    assert meetings[0].title == "Rapat Remote"
    assert meetings[0].device_id == "dev2"
    assert meetings[0].recording_dir == str(tmp_path / "dev2" / "uuid123")

    async def _get_segments():
        async with session_factory() as session:
            r = await session.execute(select(TranscriptSegment))
            return r.scalars().all()

    segments = asyncio.run(_get_segments())
    assert len(segments) == 2
    assert {s.text for s in segments} == {"Halo", "Mari mulai"}

    async def _get_summary():
        async with session_factory() as session:
            return await repo.get_summary(session, meetings[0].id)

    summary = asyncio.run(_get_summary())
    assert summary.mom_json == "{}"
    assert summary.docx_path == str(tmp_path / "dev2" / "uuid123" / "mom.docx")


def test_pull_skips_manifests_owned_by_local_device(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    fake_client.list_objects.return_value = [_fake_object("dev1/uuid123/manifest.json")]

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 0
    fake_client.get_object.assert_not_called()


def test_download_file_fetches_object_to_dest(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    dest = tmp_path / "mom.docx"

    minio_client.download_file(FakeSettings(), "dev2", "uuid123", "mom.docx", dest)

    fake_client.fget_object.assert_called_once_with("meetings", "dev2/uuid123/mom.docx", str(dest))


def test_download_file_rejects_path_traversal_in_device_id(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    try:
        minio_client.download_file(
            FakeSettings(), "../../../../etc", "uuid123", "mom.docx", tmp_path / "mom.docx",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_download_file_rejects_path_traversal_in_meeting_dir(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    try:
        minio_client.download_file(
            FakeSettings(), "dev2", "..\\..\\Windows\\System32\\evil", "mom.docx", tmp_path / "mom.docx",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_pull_skips_manifest_with_path_traversal_in_object_name(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    fake_client.list_objects.return_value = [_fake_object("../../../etc/uuid123/manifest.json")]

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 0
    fake_client.get_object.assert_not_called()


def test_pull_skips_manifests_already_known_locally(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    fake_client.list_objects.return_value = [_fake_object("dev2/uuid123/manifest.json")]

    session_factory = _make_db()

    async def _seed_existing():
        async with session_factory() as session:
            await repo.create_meeting(
                session, "Sudah Ada", None,
                recording_dir=str(tmp_path / "dev2" / "uuid123"), device_id="dev2",
            )
            await session.commit()

    asyncio.run(_seed_existing())
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 0
    fake_client.get_object.assert_not_called()


def test_pull_skips_a_malformed_object_name_without_losing_other_meetings(monkeypatch, tmp_path):
    """Regression test: object_name.split("/", 2) unpacked into 3 variables
    raises ValueError for a name with only one "/" before "manifest.json"
    (e.g. "onlyonelevel/manifest.json" -- still passes the endswith filter).
    Previously this aborted the whole pull() and, since session.commit()
    only happens once at the end, discarded every other legitimately-pulled
    meeting in the same batch too."""
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    remote_manifest = {
        "title": "Rapat Remote", "scheduled_time": None, "start_time": None, "end_time": None,
        "status": "completed", "device_id": "dev2", "device_label": "Laptop Lain",
        "segments": [], "summary": None,
    }
    fake_client.list_objects.return_value = [
        _fake_object("onlyonelevel/manifest.json"),
        _fake_object("dev2/uuid123/manifest.json"),
    ]
    fake_client.get_object.return_value = _fake_manifest_response(remote_manifest)

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 1  # the malformed entry skipped, the valid one still pulled


def test_pull_closes_and_releases_the_get_object_response(monkeypatch, tmp_path):
    """MinIO's get_object() returns an urllib3 HTTPResponse that must be
    explicitly closed and its connection released back to the pool, or
    repeated syncs against a multi-meeting bucket leak connections."""
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    remote_manifest = {
        "title": "Rapat Remote", "scheduled_time": None, "start_time": None, "end_time": None,
        "status": "completed", "device_id": "dev2", "device_label": "Laptop Lain",
        "segments": [], "summary": None,
    }
    fake_client.list_objects.return_value = [_fake_object("dev2/uuid123/manifest.json")]
    fake_response = _fake_manifest_response(remote_manifest)
    fake_client.get_object.return_value = fake_response

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    minio_client.pull(session_factory, settings)

    fake_response.close.assert_called_once()
    fake_response.release_conn.assert_called_once()
