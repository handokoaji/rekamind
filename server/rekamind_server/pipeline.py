import asyncio
import logging
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import jobs
from .deadlines import resolve_deadline
from .engines.base import AsrSegment, Engines, ExtractionInput, SpeakerTurn
from .models import Job, Meeting, Participant, Segment, Summary, Task
from .schemas import ExtractedTask
from .storage import Storage

log = logging.getLogger(__name__)


def assign_speaker(seg: AsrSegment, turns: list[SpeakerTurn]) -> str | None:
    """Label of the diarization turn overlapping `seg` the most; None if no overlap."""
    best, best_overlap = None, 0
    for t in turns:
        overlap = min(seg.end_ms, t.end_ms) - max(seg.start_ms, t.start_ms)
        if overlap > best_overlap:
            best, best_overlap = t.label, overlap
    return best


def match_participant(name: str | None, participants: list[Participant]) -> Participant | None:
    """Exact name first, then a unique first-name match. Ambiguity returns None:
    leaving the assignee unresolved for the user beats silently picking the wrong person."""
    if not name:
        return None
    n = name.strip().lower()
    named = [p for p in participants if p.name]
    exact = [p for p in named if p.name.strip().lower() == n]
    if len(exact) == 1:
        return exact[0]
    first = [p for p in named if p.name.strip().lower().split()[0] == n.split()[0]]
    return first[0] if len(first) == 1 else None


def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def dedupe_tasks(tasks: list[ExtractedTask]) -> list[ExtractedTask]:
    seen: set[tuple[str, str]] = set()
    out = []
    for t in tasks:
        key = (" ".join(t.title.lower().split()), (t.assignee or "").lower())
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


async def run_process_job(
    sf: async_sessionmaker[AsyncSession], storage: Storage, engines: Engines, job: Job
) -> None:
    """transcribe -> diarize -> merge -> extract. Heavy engine calls run in worker
    threads so the API stays responsive; each stage reports progress for the UI."""
    async with sf() as s:
        meeting = await s.get(Meeting, job.meeting_id)
        if meeting is None:
            raise RuntimeError("meeting no longer exists")
        language, title, started_at, local_name = meeting.language, meeting.title, meeting.started_at, meeting.local_user_name

    mic, spk = storage.audio_path(job.meeting_id, "mic"), storage.audio_path(job.meeting_id, "speaker")
    if not mic and not spk:
        raise RuntimeError("tidak ada file audio untuk diproses")

    await jobs.set_progress(sf, job.id, "transcribing", 5)
    mic_segs = await asyncio.to_thread(engines.transcriber.transcribe, mic, language) if mic else []
    await jobs.set_progress(sf, job.id, "transcribing", 35)
    spk_segs = await asyncio.to_thread(engines.transcriber.transcribe, spk, language) if spk else []

    await jobs.set_progress(sf, job.id, "diarizing", 55)
    # The mic channel is always the local user, so only the speaker channel needs diarization.
    turns = await asyncio.to_thread(engines.diarizer.diarize, spk) if spk and spk_segs else []

    await jobs.set_progress(sf, job.id, "merging", 70)
    async with sf() as s:
        await s.execute(delete(Segment).where(Segment.meeting_id == job.meeting_id))
        await s.execute(delete(Task).where(Task.meeting_id == job.meeting_id))
        await s.execute(delete(Summary).where(Summary.meeting_id == job.meeting_id))
        existing = (await s.execute(select(Participant).where(Participant.meeting_id == job.meeting_id))).scalars().all()
        by_label = {p.label: p for p in existing}  # re-processing keeps names the user already assigned

        def participant(label: str, *, local: bool = False) -> Participant:
            if label not in by_label:
                p = Participant(meeting_id=job.meeting_id, label=label, is_local_user=local,
                                name=local_name if local else None)
                s.add(p)
                by_label[label] = p
            return by_label[label]

        rows: list[tuple[AsrSegment, str, Participant]] = []
        for seg in mic_segs:
            rows.append((seg, "mic", participant("ME", local=True)))
        for seg in spk_segs:
            rows.append((seg, "speaker", participant(assign_speaker(seg, turns) or "UNKNOWN")))
        await s.flush()
        rows.sort(key=lambda r: r[0].start_ms)
        for seg, source, p in rows:
            s.add(Segment(meeting_id=job.meeting_id, participant_id=p.id, source=source,
                          start_ms=seg.start_ms, end_ms=seg.end_ms, text=seg.text))
        await s.commit()
        participants = list(by_label.values())
        transcript = "\n".join(f"[{_fmt(seg.start_ms)}] {p.name or p.label}: {seg.text}" for seg, _, p in rows)

    await jobs.set_progress(sf, job.id, "extracting", 80)
    result = await asyncio.to_thread(
        engines.extractor.extract,
        ExtractionInput(title=title, started_at=started_at, language=language,
                        participants=[p.name or p.label for p in participants], transcript=transcript),
    )

    meeting_day: date = started_at.date()
    async with sf() as s:
        s.add(Summary(meeting_id=job.meeting_id, overview=result.overview, decisions=result.decisions,
                      minutes=[m.model_dump() for m in result.minutes]))
        for t in dedupe_tasks(result.tasks):
            who = match_participant(t.assignee, participants)
            resolved = resolve_deadline(t.deadline_text, meeting_day)
            s.add(Task(
                meeting_id=job.meeting_id, title=t.title, description=t.description,
                assignee_name=t.assignee, assignee_participant_id=who.id if who else None,
                deadline_text=t.deadline_text,
                deadline=resolved.date if resolved else None,
                deadline_approximate=resolved.approximate if resolved else False,
                estimate_minutes=t.estimate_minutes, priority=t.priority, confidence=t.confidence,
                evidence_start_ms=t.evidence_start_ms, evidence_quote=t.evidence_quote,
            ))
        m = await s.get(Meeting, job.meeting_id)
        m.status = "review"  # a human confirms tasks before anything is exported
        await s.commit()
