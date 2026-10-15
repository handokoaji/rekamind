import asyncio
import logging
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import jobs
from .deadlines import resolve_deadline
from .engines.base import AsrSegment, Engines, ExtractionInput, SpeakerTurn
from .engines.llm import LlmError
from .models import Job, Meeting, Participant, Segment, Summary, Task
from .schemas import ExtractedTask
from .storage import Storage
from .tz import DEFAULT as DEFAULT_TZ
from .tz import to_zone, zone

log = logging.getLogger(__name__)


def assign_speaker(seg: AsrSegment, turns: list[SpeakerTurn]) -> str | None:
    """Label of the diarization turn overlapping `seg` the most; None if no overlap."""
    best, best_overlap = None, 0
    for t in turns:
        overlap = min(seg.end_ms, t.end_ms) - max(seg.start_ms, t.start_ms)
        if overlap > best_overlap:
            best, best_overlap = t.label, overlap
    return best


NEAR_MS = 3000  # a segment in a gap between turns still belongs to the speaker right next to it
MIN_RUN_WORDS = 3  # a shorter run of another speaker is diarization noise or a back-channel, not a speaker change
MIN_RUN_MS = 1000


def _label_at(ms: int, turns: list[SpeakerTurn]) -> str | None:
    """The turn containing `ms`, else the nearest turn if it is within NEAR_MS."""
    best, best_d = None, NEAR_MS + 1
    for t in turns:
        d = 0 if t.start_ms <= ms <= t.end_ms else min(abs(ms - t.start_ms), abs(ms - t.end_ms))
        if d < best_d:
            best, best_d = t.label, d
    return best


def label_segments(segs: list[AsrSegment], turns: list[SpeakerTurn], fallback: str | None = None) -> list[tuple[AsrSegment, str]]:
    """(segment, speaker label) pairs. A segment whose words are spoken by different people is cut at the change
    (the ASR cuts sentences, not speakers, so one segment used to be given to whoever spoke most of it)."""
    out: list[tuple[AsrSegment, str]] = []
    for seg in segs:
        if fallback:
            out.append((seg, fallback))
            continue
        whole = assign_speaker(seg, turns) or _label_at((seg.start_ms + seg.end_ms) // 2, turns) or "UNKNOWN"
        if len(seg.words) < 2:
            out.append((seg, whole))
            continue
        labels = [_label_at((a + b) // 2, turns) for a, b, _ in seg.words]
        known = [lab for lab in labels if lab]
        if len(set(known)) < 2:
            out.append((seg, known[0] if known else whole))
            continue
        # unlabeled words take their neighbour's label, then runs of one word are folded into the previous run
        for i, lab in enumerate(labels):
            if lab is None:
                labels[i] = next((x for x in labels[:i][::-1] if x), None) or next((x for x in labels[i:] if x), whole)
        for i in range(1, len(labels)):  # a word that continues the previous one ("coba" + "-coba") never starts a turn
            if not seg.words[i][2].startswith(" "):
                labels[i] = labels[i - 1]
        runs: list[list[int]] = []
        for i, lab in enumerate(labels):
            if runs and labels[runs[-1][0]] == lab:
                runs[-1].append(i)
            else:
                runs.append([i])

        def solid(r: list[int], seg: AsrSegment = seg) -> bool:  # long enough to be a real turn, not boundary noise or a back-channel
            return len(r) >= MIN_RUN_WORDS and seg.words[r[-1]][1] - seg.words[r[0]][0] >= MIN_RUN_MS

        merged: list[list[int]] = []
        for r in runs:
            if merged and (not solid(r) or labels[merged[-1][0]] == labels[r[0]]):
                merged[-1].extend(r)
            else:
                merged.append(list(r))
        if len(merged) > 1 and not solid(merged[0]):
            merged[1] = merged[0] + merged[1]
            merged.pop(0)
        joined: list[list[int]] = []
        for r in merged:
            if joined and labels[joined[-1][0]] == labels[r[0]]:
                joined[-1].extend(r)
            else:
                joined.append(r)
        merged = joined
        if len(merged) < 2:
            out.append((seg, labels[merged[0][0]]))
            continue
        for r in merged:
            ws = [seg.words[i] for i in r]
            out.append((AsrSegment(ws[0][0], max(ws[-1][1], ws[0][0] + 1), "".join(w[2] for w in ws).strip(), tuple(ws)),
                        labels[r[0]]))
    return out


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


FIRST_PERSON = {"saya", "aku", "gue", "gua", "gw", "i", "me", "myself"}
_TOLERANCE_MS = 2000


def speaker_at(rows: list, ms: int) -> Participant | None:
    """Who was talking at `ms`. No guess when nobody was: a wrong PIC is worse than an empty one."""
    for seg, _source, p in rows:
        if seg.start_ms - _TOLERANCE_MS <= ms <= seg.end_ms + _TOLERANCE_MS:
            return p
    return None


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
    sf: async_sessionmaker[AsyncSession], storage: Storage, engines: Engines, job: Job, tz: ZoneInfo | None = None
) -> None:
    """transcribe -> diarize -> merge -> extract. Heavy engine calls run in worker
    threads so the API stays responsive; each stage reports progress for the UI."""
    tz = tz or zone(DEFAULT_TZ)
    async with sf() as s:
        meeting = await s.get(Meeting, job.meeting_id)
        if meeting is None:
            raise RuntimeError("meeting no longer exists")
        language, title, local_name = meeting.language, meeting.title, meeting.local_user_name
        # In the meeting's own zone: "besok" at 01:00 WIB is the day after the WIB date, not after the UTC date.
        started_at = to_zone(meeting.started_at, tz)

    notes: list[str] = []  # things that went wrong without making the meeting useless; shown to the user
    if job.kind == "extract":
        # Retry of the summary/tasks only: the transcript is already saved, so this costs one LLM call.
        async with sf() as s:
            existing = (await s.execute(select(Participant).where(Participant.meeting_id == job.meeting_id))).scalars().all()
            by_id = {p.id: p for p in existing}
            segs = (await s.execute(select(Segment).where(Segment.meeting_id == job.meeting_id).order_by(Segment.start_ms))).scalars().all()
            await s.execute(delete(Task).where(Task.meeting_id == job.meeting_id))
            await s.execute(delete(Summary).where(Summary.meeting_id == job.meeting_id))
            await s.commit()
        if not segs:
            raise RuntimeError("belum ada transkrip untuk diringkas; proses rapat dari awal")
        participants = list(existing)
        rows = [(AsrSegment(seg.start_ms, seg.end_ms, seg.text), seg.source, by_id[seg.participant_id]) for seg in segs if seg.participant_id in by_id]
    else:
        rows, participants = await _transcribe_and_store(sf, storage, engines, job, language, local_name, notes)
    transcript = "\n".join(f"[{_fmt(seg.start_ms)}] {p.name or p.label}: {seg.text}" for seg, _, p in rows)

    await jobs.set_progress(sf, job.id, "extracting", 80)
    result = None
    if not rows:
        # Nothing was said (or detected): an LLM call would only produce an empty summary and spend quota.
        notes.append("Tidak ada ucapan terdeteksi dalam rekaman ini, jadi ringkasan dan task tidak dibuat.")
    else:
        try:
            result = await asyncio.to_thread(
                engines.extractor.extract,
                ExtractionInput(title=title, started_at=started_at, language=language,
                                participants=[p.name or p.label for p in participants], transcript=transcript),
            )
        except LlmError as exc:
            # The transcript is the expensive part and it is saved: keep it, say what is missing, offer a retry.
            log.warning("extraction failed for %s: %s", job.meeting_id, exc)
            notes.append(f"Ringkasan dan task belum dibuat: {exc}. Transkrip tersimpan; tekan \"Buat ulang ringkasan\" setelah masalahnya teratasi.")
            result = None

    meeting_day: date = started_at.date()
    async with sf() as s:
        if result is not None:
            s.add(Summary(meeting_id=job.meeting_id, overview=result.overview, decisions=result.decisions,
                          minutes=[m.model_dump() for m in result.minutes]))
        new_tasks = dedupe_tasks(result.tasks if result is not None else [])
        for t in new_tasks:
            who = match_participant(t.assignee, participants)
            if who is None and t.assignee and t.assignee.strip().lower() in FIRST_PERSON and t.evidence_start_ms is not None:
                who = speaker_at(rows, t.evidence_start_ms)  # "Saya kirim laporan" -> whoever said it
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
        # A human confirms tasks before anything is exported. With no task to confirm there is nothing to review (the
        # only way out of "review" is deciding a task, so it would stay there forever); a failed summary stays in
        # "review" because it has a retry ("Buat ulang ringkasan").
        summary_failed = result is None and bool(rows)
        m.status = "review" if (new_tasks or summary_failed) else "done"
        m.error = " ".join(notes) or None
        await s.commit()


async def _transcribe_and_store(sf, storage, engines, job, language, local_name, notes):
    """transcribe -> diarize -> merge; stores segments and participants. Returns (rows, participants)."""
    mic, spk = await storage.audio_path(job.meeting_id, "mic"), await storage.audio_path(job.meeting_id, "speaker")
    if not mic and not spk:
        raise RuntimeError("tidak ada file audio untuk diproses")

    await jobs.set_progress(sf, job.id, "transcribing", 5)
    mic_segs = await asyncio.to_thread(engines.transcriber.transcribe, mic, language) if mic else []
    await jobs.set_progress(sf, job.id, "transcribing", 35)
    spk_segs = await asyncio.to_thread(engines.transcriber.transcribe, spk, language) if spk else []

    await jobs.set_progress(sf, job.id, "diarizing", 55)
    # The mic channel is always the local user, so only the speaker channel needs diarization.
    turns: list[SpeakerTurn] = []
    fallback_label = None
    if spk and spk_segs:
        try:
            async with sf() as s:
                m = await s.get(Meeting, job.meeting_id)
                num_speakers = m.num_speakers if m else None
            turns = await asyncio.to_thread(engines.diarizer.diarize, spk, num_speakers)
        except Exception as exc:  # noqa: BLE001 - a missing optional model must not throw the transcript away
            log.warning("diarization failed for %s: %s", job.meeting_id, exc)
            notes.append(f"Pemisah pembicara gagal ({type(exc).__name__}: {exc}); semua suara komputer ditandai satu pembicara.")
            fallback_label = "SPEAKER_00"

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
        for seg, label in label_segments(spk_segs, turns, fallback_label):
            rows.append((seg, "speaker", participant(label)))
        await s.flush()
        rows.sort(key=lambda r: r[0].start_ms)
        for seg, source, p in rows:
            s.add(Segment(meeting_id=job.meeting_id, participant_id=p.id, source=source,
                          start_ms=seg.start_ms, end_ms=seg.end_ms, text=seg.text))
        # A re-run can use fewer speakers than the last one; a leftover SPEAKER_03 with nothing said would still be
        # counted as a detected person.
        used = {p.id for _, _, p in rows}
        for p in by_label.values():
            if p.id not in used:
                await s.delete(p)
        await s.commit()
        return rows, [p for p in by_label.values() if p.id in used]
