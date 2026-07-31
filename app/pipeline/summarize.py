import json
from datetime import datetime
from pathlib import Path

from app.storage import repository as repo
from app.storage.models import Summary
from app.summarization.docx_export import export_mom_docx
from app.summarization.groq_client import GroqSummarizer


async def summarize_and_export(
    session_factory,
    meeting_id: int,
    meeting_title: str,
    meeting_date: datetime,
    docx_output_path: Path,
    summarizer: GroqSummarizer,
) -> Summary:
    async with session_factory() as session:
        await repo.mark_meeting_status(session, meeting_id, "summarizing")
        await session.commit()

    async with session_factory() as session:
        rows = await repo.get_final_transcript(session, meeting_id)
    transcript_text = "\n".join(f"{label}: {text}" for label, text in rows)

    try:
        mom = summarizer.summarize(meeting_title, transcript_text)
        docx_path = export_mom_docx(meeting_title, meeting_date, mom, docx_output_path)
        mom_json = json.dumps({
            "minute_by_minute": mom.minute_by_minute,
            "decisions": mom.decisions,
            "action_items": mom.action_items,
            "detailed_notes": mom.detailed_notes,
        })
        async with session_factory() as session:
            summary = await repo.save_summary(
                session, meeting_id, mom_json=mom_json, docx_path=str(docx_path),
                groq_model=summarizer.model, status="ready",
            )
            await repo.mark_meeting_status(session, meeting_id, "completed")
            await session.commit()
        return summary
    except Exception as exc:
        async with session_factory() as session:
            await repo.mark_meeting_failed(session, meeting_id, "summarize", str(exc))
            await session.commit()
        raise
