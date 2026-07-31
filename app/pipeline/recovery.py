import logging
from pathlib import Path

from app.storage import repository as repo

logger = logging.getLogger(__name__)


async def recover_abandoned_meetings(session_factory) -> list[int]:
    """Finds meetings orphaned by a crash (stuck in recording/transcribing/
    summarizing -- a normal flow always reaches a resting status: recorded,
    transcribed, completed, or failed) and resets each to the right resting
    status based on what actually made it to disk/DB before the crash. Never
    runs the heavy pipeline itself -- the meeting just reappears in Riwayat
    ready for its next manual action, same as any other meeting.

    Returns the ids of meetings it touched.
    """
    async with session_factory() as session:
        abandoned = await repo.find_abandoned_meetings(session)

    recovered_ids = []
    for meeting in abandoned:
        recovered_ids.append(meeting.id)
        async with session_factory() as session:
            if meeting.status == "recording":
                await _recover_recording(session, meeting)
            elif meeting.status == "transcribing":
                await _recover_transcribing(session, meeting)
            elif meeting.status == "summarizing":
                await _recover_summarizing(session, meeting)
            await session.commit()
    return recovered_ids


async def _recover_recording(session, meeting) -> None:
    mic_wav, speaker_wav = _recording_paths(meeting)
    if mic_wav is not None and mic_wav.exists() and speaker_wav.exists():
        await repo.mark_meeting_status(session, meeting.id, "recorded")
    else:
        logger.warning("meeting %s: no recording found after crash", meeting.id)
        await repo.mark_meeting_failed(session, meeting.id, "transcribe", "Rekaman tidak ditemukan setelah crash")


async def _recover_transcribing(session, meeting) -> None:
    if await repo.has_final_segments(session, meeting.id):
        await repo.mark_meeting_status(session, meeting.id, "transcribed")
    else:
        await repo.mark_meeting_status(session, meeting.id, "recorded")


async def _recover_summarizing(session, meeting) -> None:
    summary = await repo.get_summary(session, meeting.id)
    if summary is not None and summary.status == "ready":
        await repo.mark_meeting_status(session, meeting.id, "completed")
    else:
        await repo.mark_meeting_status(session, meeting.id, "transcribed")


def _recording_paths(meeting) -> tuple[Path | None, Path | None]:
    if not meeting.recording_dir:
        return None, None
    recording_dir = Path(meeting.recording_dir)
    return recording_dir / "mic.wav", recording_dir / "speaker.wav"
