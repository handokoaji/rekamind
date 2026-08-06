import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.storage.models import Meeting, Speaker, Summary, TranscriptSegment
from app.storage import repository as repo

# Meeting.status's state-machine order (see app/storage/models.py) -- pull()
# uses this to only ever move a locally-known meeting FORWARD, never let a
# stale/out-of-order manifest (e.g. from a device that pulled before someone
# else finished processing it) clobber further-along local progress. "failed"
# deliberately never overwrites anything: a stale failure from a run that's
# since been retried elsewhere shouldn't stick.
_STATUS_ORDER = {
    "scheduled": 0, "recording": 1, "recorded": 2, "transcribing": 3,
    "transcribed": 4, "summarizing": 5, "completed": 6, "failed": -1,
}

# meeting_dir is always uuid4().hex on the writing side, and device_id is
# either that or a sanitized hostname (see Settings._default_device_identity)
# -- but pull() derives both from MinIO object names -- data written by
# other, potentially untrusted or compromised devices sharing the same
# bucket. A malicious "../../.." component there would otherwise let a
# remote object name control where pull() writes on this local filesystem
# (path traversal). Restricting to this charset covers everything either
# source legitimately produces.
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
    from urllib.parse import urlsplit

    from minio import Minio

    endpoint = settings.minio_endpoint
    secure = True
    if "://" in endpoint:
        # minio-py's `endpoint` arg is host:port only -- scheme goes in
        # `secure` instead. Users naturally paste the full URL MinIO's own
        # console shows them, so strip it rather than rejecting it.
        parsed = urlsplit(endpoint)
        secure = parsed.scheme != "http"
        endpoint = parsed.netloc
    return Minio(
        endpoint, access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key, secure=secure,
    )


def push(session_factory, settings) -> dict:
    import asyncio

    async def _run():
        client = _client(settings)
        manifests = 0
        uploaded = 0
        async with session_factory() as session:
            # Not just this device's own meetings any more: a meeting pulled
            # from another device and then transcribed/summarized HERE (see
            # RecorderController._ensure_audio_files) needs its result pushed
            # back too, so it becomes visible to the original owner and any
            # other device on the next pull.
            result = await session.execute(select(Meeting).where(Meeting.deleted_at.is_(None)))
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

                is_own = meeting.device_id == settings.device_id
                # A meeting only ever pulled here (browsed, never processed) has
                # nothing new to contribute -- pushing it back would overwrite
                # the owner's manifest with a stale copy of what we pulled
                # earlier, since this device has no way to know if the owner
                # has since moved it further along themselves.
                if not is_own and not segments and summary is None:
                    continue

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
                    # For a foreign meeting, mic.wav/speaker.wav were fetched
                    # FROM this exact prefix in the first place (see
                    # _ensure_audio_files) -- re-uploading them back would just
                    # waste bandwidth on a (potentially huge) unchanged file.
                    # Only mom.docx can be genuinely new here.
                    filenames = ("mic.wav", "speaker.wav", "mom.docx") if is_own else ("mom.docx",)
                    for filename in filenames:
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
                if not (_is_safe_path_component(device_id) and _is_safe_path_component(meeting_uuid)):
                    continue  # malformed/malicious object name -- skip, don't let it touch the filesystem
                recordings_root = Path(settings.recordings_dir).resolve()
                # A manifest under our OWN device_id prefix isn't necessarily one
                # we wrote: another device may have transcribed one of our
                # meetings (see push()'s "foreign meeting processed here" case)
                # and pushed the result back to OUR prefix so we'd pick it up.
                # Our own meetings live at recordings_dir/<uuid> (no device_id
                # folder -- see start_meeting/import_meeting), unlike a pulled
                # copy of someone else's, which lives at
                # recordings_dir/<their_device_id>/<uuid>.
                is_own_meeting = device_id == settings.device_id
                if is_own_meeting:
                    recording_dir = (recordings_root / meeting_uuid).resolve()
                else:
                    recording_dir = (recordings_root / device_id / meeting_uuid).resolve()
                if not recording_dir.is_relative_to(recordings_root):
                    continue  # defense in depth -- should be unreachable once the charset check above passes
                existing_result = await session.execute(
                    select(Meeting).where(Meeting.recording_dir == str(recording_dir))
                )
                existing = existing_result.scalar_one_or_none()
                if is_own_meeting and existing is None:
                    # A manifest claiming to be ours but matching no meeting we
                    # actually have locally -- never fabricate a new "own"
                    # meeting from someone else's write into our prefix.
                    continue

                response = client.get_object(settings.minio_bucket, obj.object_name)
                try:
                    manifest = json.loads(response.read())
                finally:
                    response.close()
                    response.release_conn()
                remote_status = manifest["status"]

                if existing is not None:
                    # Someone (possibly a third device) has moved this meeting
                    # further along since we first pulled it -- refresh our
                    # copy so Transkrip/Ringkasan/Lihat Transkrip reflect it.
                    # Never move status BACKWARD: an in-flight local action
                    # (e.g. this device is mid-Transkrip on the same foreign
                    # meeting right now) must not be clobbered by a manifest
                    # that just hasn't caught up yet.
                    if _STATUS_ORDER.get(remote_status, 0) <= _STATUS_ORDER.get(existing.status, 0):
                        continue
                    meeting = existing
                    meeting.status = remote_status
                    meeting.start_time = _parse_iso(manifest.get("start_time"))
                    meeting.end_time = _parse_iso(manifest.get("end_time"))
                    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id))
                    await session.execute(delete(Summary).where(Summary.meeting_id == meeting.id))
                else:
                    meeting = Meeting(
                        title=manifest["title"],
                        scheduled_time=_parse_iso(manifest.get("scheduled_time")),
                        start_time=_parse_iso(manifest.get("start_time")),
                        end_time=_parse_iso(manifest.get("end_time")),
                        status=remote_status, device_id=manifest["device_id"],
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
