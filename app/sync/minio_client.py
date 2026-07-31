import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.storage.models import Meeting, Speaker, Summary, TranscriptSegment
from app.storage import repository as repo

# device_id and meeting_dir are always uuid4().hex on the writing side, but
# pull() derives them from MinIO object names -- data written by other,
# potentially untrusted or compromised devices sharing the same bucket. A
# malicious "../../.." component there would otherwise let a remote object
# name control where pull() writes on this local filesystem (path
# traversal). Restricting to this charset also happens to be exactly what
# uuid4().hex ever produces, so it rejects nothing legitimate.
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_path_component(value: str) -> bool:
    return bool(_SAFE_PATH_COMPONENT.match(value))


def is_configured(settings) -> bool:
    return settings.minio_is_configured


def manifest_object_prefix(device_id: str, meeting_dir_uuid: str) -> str:
    return f"{device_id}/{meeting_dir_uuid}"


def build_manifest(meeting, segments, speakers_by_id: dict, summary) -> dict:
    def _label(seg):
        if seg.speaker_id is None:
            return "Anda"
        return speakers_by_id[seg.speaker_id].label

    return {
        "title": meeting.title,
        "scheduled_time": meeting.scheduled_time.isoformat() if meeting.scheduled_time else None,
        "start_time": meeting.start_time.isoformat() if meeting.start_time else None,
        "end_time": meeting.end_time.isoformat() if meeting.end_time else None,
        "status": meeting.status,
        "device_id": meeting.device_id,
        "device_label": meeting.device_label,
        "segments": [
            {
                "speaker_label": _label(seg), "source": seg.source,
                "start_ms": seg.start_ms, "end_ms": seg.end_ms, "text": seg.text,
            }
            for seg in segments if seg.is_final
        ],
        "summary": (
            {
                "mom_json": summary.mom_json, "has_docx": summary.docx_path is not None,
                "groq_model": summary.groq_model, "status": summary.status,
            }
            if summary is not None else None
        ),
    }


def _client(settings):
    from minio import Minio
    return Minio(
        settings.minio_endpoint, access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
    )


def push(session_factory, settings) -> dict:
    import asyncio

    async def _run():
        client = _client(settings)
        manifests = 0
        uploaded = 0
        async with session_factory() as session:
            result = await session.execute(select(Meeting).where(Meeting.device_id == settings.device_id))
            meetings = list(result.scalars().all())
            for meeting in meetings:
                if not meeting.recording_dir:
                    continue
                seg_result = await session.execute(
                    select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id)
                )
                segments = list(seg_result.scalars().all())
                speaker_result = await session.execute(
                    select(Speaker).where(Speaker.meeting_id == meeting.id)
                )
                speakers_by_id = {s.id: s for s in speaker_result.scalars().all()}
                summary = await repo.get_summary(session, meeting.id)

                manifest = build_manifest(meeting, segments, speakers_by_id, summary)
                prefix = manifest_object_prefix(meeting.device_id, Path(meeting.recording_dir).name)
                manifest_bytes = json.dumps(manifest).encode("utf-8")
                client.put_object(
                    settings.minio_bucket, f"{prefix}/manifest.json",
                    io.BytesIO(manifest_bytes), length=len(manifest_bytes),
                )
                manifests += 1

                if meeting.synced_at is None:
                    recording_dir = Path(meeting.recording_dir)
                    any_uploaded = False
                    for filename in ("mic.wav", "speaker.wav", "mom.docx"):
                        local_path = recording_dir / filename
                        if local_path.exists():
                            client.fput_object(settings.minio_bucket, f"{prefix}/{filename}", str(local_path))
                            uploaded += 1
                            any_uploaded = True
                    # Not yet: syncing before any file has been written (e.g. right
                    # after meeting creation) must not permanently mark this meeting
                    # "synced" -- that would skip the file-upload block on every
                    # later sync, forever, once the files finally do exist.
                    if any_uploaded:
                        meeting.synced_at = datetime.now(timezone.utc)
            await session.commit()
        return {"manifests": manifests, "uploaded": uploaded}

    return asyncio.run(_run())


def _parse_iso(value: str | None):
    return datetime.fromisoformat(value) if value else None


def pull(session_factory, settings) -> dict:
    import asyncio

    async def _run():
        client = _client(settings)
        pulled = 0
        async with session_factory() as session:
            for obj in client.list_objects(settings.minio_bucket, recursive=True):
                if not obj.object_name.endswith("/manifest.json"):
                    continue
                parts = obj.object_name.split("/", 2)
                if len(parts) != 3:
                    continue  # not <device_id>/<meeting_uuid>/manifest.json -- malformed, skip
                device_id, meeting_uuid, _ = parts
                if device_id == settings.device_id:
                    continue
                if not (_is_safe_path_component(device_id) and _is_safe_path_component(meeting_uuid)):
                    continue  # malformed/malicious object name -- skip, don't let it touch the filesystem
                recordings_root = Path(settings.recordings_dir).resolve()
                recording_dir = (recordings_root / device_id / meeting_uuid).resolve()
                if not recording_dir.is_relative_to(recordings_root):
                    continue  # defense in depth -- should be unreachable once the charset check above passes
                existing = await session.execute(
                    select(Meeting).where(Meeting.recording_dir == str(recording_dir))
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                response = client.get_object(settings.minio_bucket, obj.object_name)
                try:
                    manifest = json.loads(response.read())
                finally:
                    response.close()
                    response.release_conn()

                meeting = Meeting(
                    title=manifest["title"],
                    scheduled_time=_parse_iso(manifest.get("scheduled_time")),
                    start_time=_parse_iso(manifest.get("start_time")),
                    end_time=_parse_iso(manifest.get("end_time")),
                    status=manifest["status"], device_id=manifest["device_id"],
                    device_label=manifest.get("device_label"), recording_dir=str(recording_dir),
                )
                session.add(meeting)
                await session.flush()

                label_to_speaker_id: dict[str, int | None] = {"Anda": None}
                for seg in manifest["segments"]:
                    label = seg["speaker_label"]
                    if label not in label_to_speaker_id:
                        speaker = await repo.get_or_create_speaker(session, meeting.id, label)
                        label_to_speaker_id[label] = speaker.id
                    session.add(TranscriptSegment(
                        meeting_id=meeting.id, speaker_id=label_to_speaker_id[label],
                        source=seg["source"], start_ms=seg["start_ms"], end_ms=seg["end_ms"],
                        text=seg["text"], is_final=True,
                    ))

                if manifest.get("summary"):
                    s = manifest["summary"]
                    session.add(Summary(
                        meeting_id=meeting.id, mom_json=s["mom_json"],
                        docx_path=str(recording_dir / "mom.docx") if s.get("has_docx") else None,
                        groq_model=s.get("groq_model", ""), status=s.get("status", "ready"),
                    ))
                pulled += 1
            await session.commit()
        return {"pulled": pulled}

    return asyncio.run(_run())


def download_file(settings, device_id: str, meeting_dir: str, filename: str, dest: Path) -> None:
    if not (_is_safe_path_component(device_id) and _is_safe_path_component(meeting_dir)):
        raise ValueError(f"unsafe device_id/meeting_dir for MinIO download: {device_id!r}/{meeting_dir!r}")
    client = _client(settings)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.fget_object(settings.minio_bucket, f"{device_id}/{meeting_dir}/{filename}", str(dest))
