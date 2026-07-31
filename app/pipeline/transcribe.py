from pathlib import Path

from app.asr.base import TranscriberBackend
from app.pipeline.merge import merge_segments
from app.storage import repository as repo


async def transcribe_and_diarize(
    session_factory,
    meeting_id: int,
    mic_wav: Path,
    speaker_wav: Path,
    transcriber: TranscriberBackend,
    diarizer,
) -> None:
    async with session_factory() as session:
        await repo.mark_meeting_status(session, meeting_id, "transcribing")
        await session.commit()

    try:
        mic_segments = transcriber.transcribe(mic_wav, language="id")
        speaker_segments = transcriber.transcribe(speaker_wav, language="id")
        speaker_labels = diarizer.diarize(speaker_wav)
        merged = merge_segments(mic_segments, speaker_segments, speaker_labels)

        async with session_factory() as session:
            label_to_speaker_id: dict[str, int | None] = {"Anda": None}
            segment_rows = []
            for seg in merged:
                speaker_id = None
                if seg.speaker_label != "Anda":
                    if seg.speaker_label not in label_to_speaker_id:
                        speaker = await repo.get_or_create_speaker(session, meeting_id, seg.speaker_label)
                        label_to_speaker_id[seg.speaker_label] = speaker.id
                    speaker_id = label_to_speaker_id[seg.speaker_label]
                segment_rows.append({
                    "meeting_id": meeting_id,
                    "speaker_id": speaker_id,
                    "source": seg.source,
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "text": seg.text,
                })
            # All segments, not just drafts: a second run (retry, double-click)
            # must replace the previous transcript instead of appending to it.
            await repo.clear_all_segments(session, meeting_id)
            await repo.save_transcript_segments(session, segment_rows)
            await repo.mark_meeting_status(session, meeting_id, "transcribed")
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            await repo.mark_meeting_failed(session, meeting_id, "transcribe", str(exc))
            await session.commit()
        raise
