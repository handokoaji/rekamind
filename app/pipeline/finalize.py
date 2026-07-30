import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.asr.base import TranscriberBackend
from app.pipeline.merge import merge_segments
from app.storage import repository as repo
from app.storage.models import Summary
from app.summarization.docx_export import export_mom_docx
from app.summarization.groq_client import GroqSummarizer


async def finalize_meeting(
    session: AsyncSession,
    meeting_id: int,
    meeting_title: str,
    meeting_date: datetime,
    mic_wav: Path,
    speaker_wav: Path,
    transcriber: TranscriberBackend,
    diarizer,
    summarizer: GroqSummarizer,
    docx_output_path: Path,
) -> Summary:
    mic_segments = transcriber.transcribe(mic_wav, language="id")
    speaker_segments = transcriber.transcribe(speaker_wav, language="id")
    speaker_labels = diarizer.diarize(speaker_wav)
    merged = merge_segments(mic_segments, speaker_segments, speaker_labels)

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
    await repo.save_transcript_segments(session, segment_rows)
    # Commit the transcript before the risky LLM/docx step: spec §9 requires the
    # transcript to survive intact even when Groq fails.
    await session.commit()

    transcript_text = "\n".join(f"{seg.speaker_label}: {seg.text}" for seg in merged)
    try:
        mom = summarizer.summarize(meeting_title, transcript_text)
        docx_path = export_mom_docx(meeting_title, meeting_date, mom, docx_output_path)
        mom_json = json.dumps({
            "minute_by_minute": mom.minute_by_minute,
            "decisions": mom.decisions,
            "action_items": mom.action_items,
            "detailed_notes": mom.detailed_notes,
        })
        summary = await repo.save_summary(
            session, meeting_id, mom_json=mom_json, docx_path=str(docx_path),
            groq_model=summarizer.model, status="ready",
        )
        await repo.mark_meeting_status(session, meeting_id, "completed")
        await session.commit()
        return summary
    except Exception:
        # Roll back only the summary work; the transcript above is already committed.
        await session.rollback()
        await repo.save_summary(
            session, meeting_id, mom_json="{}", docx_path=None,
            groq_model=summarizer.model, status="failed",
        )
        await repo.mark_meeting_status(session, meeting_id, "failed")
        await session.commit()
        raise
