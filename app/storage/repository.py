from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import Meeting, Recording, Speaker, Summary, TranscriptSegment


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_meeting(session: AsyncSession, title: str, scheduled_time: datetime | None) -> Meeting:
    meeting = Meeting(title=title, scheduled_time=scheduled_time, status="scheduled")
    session.add(meeting)
    await session.flush()
    return meeting


async def start_recording(session: AsyncSession, meeting_id: int) -> None:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} not found")
    meeting.status = "recording"
    meeting.start_time = _utcnow()


async def stop_recording(session: AsyncSession, meeting_id: int) -> None:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} not found")
    meeting.status = "processing"
    meeting.end_time = _utcnow()


async def save_recording_file(
    session: AsyncSession, meeting_id: int, file_path: str, source: str, duration_ms: int
) -> Recording:
    recording = Recording(meeting_id=meeting_id, file_path=file_path, source=source, duration_ms=duration_ms)
    session.add(recording)
    await session.flush()
    return recording


async def get_or_create_speaker(session: AsyncSession, meeting_id: int, label: str) -> Speaker:
    result = await session.execute(
        select(Speaker).where(Speaker.meeting_id == meeting_id, Speaker.label == label)
    )
    speaker = result.scalar_one_or_none()
    if speaker is not None:
        return speaker
    speaker = Speaker(meeting_id=meeting_id, label=label)
    session.add(speaker)
    await session.flush()
    return speaker


async def save_transcript_segments(session: AsyncSession, segments: list[dict]) -> None:
    for seg in segments:
        session.add(TranscriptSegment(
            meeting_id=seg["meeting_id"],
            speaker_id=seg.get("speaker_id"),
            source=seg["source"],
            start_ms=seg["start_ms"],
            end_ms=seg["end_ms"],
            text=seg["text"],
            is_final=seg.get("is_final", True),
        ))
    await session.flush()


async def clear_draft_segments(session: AsyncSession, meeting_id: int) -> None:
    await session.execute(
        delete(TranscriptSegment).where(
            TranscriptSegment.meeting_id == meeting_id,
            TranscriptSegment.is_final.is_(False),
        )
    )
    await session.flush()


async def save_summary(
    session: AsyncSession, meeting_id: int, mom_json: str, docx_path: str | None,
    groq_model: str, status: str,
) -> Summary:
    summary = Summary(
        meeting_id=meeting_id, mom_json=mom_json, docx_path=docx_path,
        groq_model=groq_model, status=status,
    )
    session.add(summary)
    await session.flush()
    return summary


async def mark_meeting_status(session: AsyncSession, meeting_id: int, status: str) -> None:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} not found")
    meeting.status = status


async def list_meetings(session: AsyncSession) -> list[Meeting]:
    result = await session.execute(select(Meeting).order_by(Meeting.created_at.desc()))
    return list(result.scalars().all())
