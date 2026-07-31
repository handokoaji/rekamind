from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import Meeting, Recording, Speaker, Summary, TranscriptSegment


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_meeting(
    session: AsyncSession, title: str, scheduled_time: datetime | None,
    recording_dir: str | None = None,
) -> Meeting:
    meeting = Meeting(
        title=title, scheduled_time=scheduled_time, status="scheduled",
        recording_dir=recording_dir,
    )
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
    meeting.status = "recorded"
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


async def find_abandoned_meetings(session: AsyncSession) -> list[Meeting]:
    """A meeting stuck in recording/transcribing/summarizing never reached a
    terminal or resting status (recorded/transcribed/completed/failed) -- the
    only way that happens is the app dying mid-action, e.g. a crash."""
    result = await session.execute(
        select(Meeting).where(Meeting.status.in_(["recording", "transcribing", "summarizing"]))
    )
    return list(result.scalars().all())


async def mark_meeting_failed(session: AsyncSession, meeting_id: int, stage: str, error_message: str) -> None:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} not found")
    meeting.status = "failed"
    meeting.failed_stage = stage
    meeting.error_message = error_message


async def has_final_segments(session: AsyncSession, meeting_id: int) -> bool:
    result = await session.execute(
        select(TranscriptSegment.id).where(
            TranscriptSegment.meeting_id == meeting_id,
            TranscriptSegment.is_final.is_(True),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_final_transcript(session: AsyncSession, meeting_id: int) -> list[tuple[str, str]]:
    """[(speaker_label, text), ...] ordered by start_ms, read straight from the
    DB so summarize_and_export never needs the in-memory result of an earlier
    transcribe_and_diarize call -- they can run in different app sessions."""
    result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting_id, TranscriptSegment.is_final.is_(True))
        .order_by(TranscriptSegment.start_ms)
    )
    rows = []
    for seg in result.scalars().all():
        if seg.speaker_id is None:
            label = "Anda"
        else:
            speaker = await session.get(Speaker, seg.speaker_id)
            label = speaker.label if speaker else "Speaker ?"
        rows.append((label, seg.text))
    return rows


async def get_summary(session: AsyncSession, meeting_id: int) -> Summary | None:
    result = await session.execute(select(Summary).where(Summary.meeting_id == meeting_id))
    return result.scalar_one_or_none()
