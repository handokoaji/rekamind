# Fase 3 — Riwayat Meeting & Proses Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple recording from processing. "Stop Rekam" saves WAV and marks the meeting `recorded` — nothing heavy runs automatically. Transcription and summarization become manual, per-meeting, retryable actions triggered from a new "Riwayat" history tab, and can run concurrently with recording a new meeting.

**Architecture:** `app/pipeline/finalize.py` (single function, auto-run after Stop) is replaced by two independent, DB-driven functions — `transcribe_and_diarize()` and `summarize_and_export()` — each opening its own sessions via `session_factory` (not a shared caller session) so they can be triggered independently, any time, from any UI action. `RecorderController` gains `run_transcribe()`/`run_summarize()`/`retry()` plus read-only `list_meetings()`/`get_transcript()`/`get_docx_path()` for the new `HistoryView` widget. `MainWindow` becomes two tab frames raised via `tkraise()` inside a shared container. Crash recovery (`app/pipeline/recovery.py`, already scaffolded) is rewritten to just reset a stuck meeting's status instead of re-running the full pipeline.

**Tech Stack:** Python 3.14, Tkinter (`ttk.Treeview` for the history list — stdlib, no new dependency), SQLAlchemy 2.0 async ORM, existing ASR/diarization/Groq/docx modules (unchanged).

## Global Constraints

- No new dependencies — `ttk.Treeview` (stdlib) is the history list widget.
- Never commit `.env` or real credentials (standing rule, unrelated files only).
- Use `git add <specific files>` by name in every commit — never `git add -A`/`git add .`.
- Bahasa Indonesia for all user-facing strings (labels, status text, error messages), matching the rest of the app.
- Every new async DB function opens its own session via a `session_factory` parameter (not a shared caller session) unless explicitly chaining within one commit boundary — this is what makes actions independently triggerable from separate button clicks / background threads.
- Follow existing test conventions exactly: in-memory `sqlite+aiosqlite:///:memory:` via `make_engine`/`init_db`/`make_session_factory`, fakes/mocks for transcriber/diarizer/summarizer, `asyncio.run(scenario())` wrapping async test bodies.
- The live Postgres DB at `10.55.11.209` needs the same new columns added manually via `ALTER TABLE` after each model change (SQLAlchemy's `create_all` only creates missing tables, never alters existing ones) — call this out explicitly in Task 1's steps, using the `.venv` python + `app.config.get_settings()` pattern already used earlier this session, not raw SQL with hand-typed credentials.

---

## Task 1: Schema & repository foundation

**Files:**
- Modify: `app/storage/models.py:15-33` (`Meeting` class)
- Modify: `app/storage/repository.py` (`stop_recording`, `find_abandoned_meetings`; add `mark_meeting_failed`, `has_final_segments`, `get_final_transcript`, `get_summary`)
- Test: `tests/storage/test_models.py`
- Test: `tests/storage/test_repository.py`

**Interfaces:**
- Produces: `Meeting.error_message: str | None`, `Meeting.failed_stage: str | None` (columns)
- Produces: `repo.mark_meeting_failed(session, meeting_id: int, stage: str, error_message: str) -> None`
- Produces: `repo.has_final_segments(session, meeting_id: int) -> bool`
- Produces: `repo.get_final_transcript(session, meeting_id: int) -> list[tuple[str, str]]` — `[(speaker_label, text), ...]` ordered by `start_ms`, `"Anda"` for `speaker_id is None`
- Produces: `repo.get_summary(session, meeting_id: int) -> Summary | None`
- Changes: `repo.stop_recording()` now sets `status = "recorded"` (was `"processing"`)
- Changes: `repo.find_abandoned_meetings()` now matches `status.in_(["recording", "transcribing", "summarizing"])` (was `["recording", "processing"]` — `"processing"` no longer exists as a status anywhere in the app after this plan)

- [ ] **Step 1: Write the failing tests**

Append to `tests/storage/test_models.py`:

```python
def test_meeting_failure_fields_round_trip():
    async def scenario():
        session_factory = await _make_session_factory()
        async with session_factory() as session:
            meeting = Meeting(
                title="Standup", status="failed",
                failed_stage="transcribe", error_message="CUDA out of memory",
            )
            session.add(meeting)
            await session.commit()
            return meeting.id

        return meeting.id

    meeting_id = asyncio.run(scenario())
    assert isinstance(meeting_id, int)
```

Append to `tests/storage/test_repository.py`:

```python
def test_stop_recording_sets_status_to_recorded():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await repo.start_recording(session, meeting.id)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.stop_recording(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "recorded"


def test_mark_meeting_failed_sets_stage_and_message():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.mark_meeting_failed(session, meeting_id, "summarize", "Groq timeout")
            await session.commit()

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "failed"
    assert meetings[0].failed_stage == "summarize"
    assert meetings[0].error_message == "Groq timeout"


def test_has_final_segments_true_only_for_is_final_true():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            before = await repo.has_final_segments(session, meeting_id)
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "draft", "is_final": False},
            ])
            await session.commit()

        async with session_factory() as session:
            only_draft = await repo.has_final_segments(session, meeting_id)
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "final", "is_final": True},
            ])
            await session.commit()

        async with session_factory() as session:
            with_final = await repo.has_final_segments(session, meeting_id)

        return before, only_draft, with_final

    before, only_draft, with_final = asyncio.run(scenario())
    assert before is False
    assert only_draft is False
    assert with_final is True


def test_get_final_transcript_orders_by_start_ms_and_resolves_labels():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            speaker = await repo.get_or_create_speaker(session, meeting_id, "Speaker 1")
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": speaker.id, "source": "speaker",
                 "start_ms": 600, "end_ms": 1200, "text": "Mari mulai"},
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "Selamat pagi"},
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 100, "end_ms": 200, "text": "draft lama", "is_final": False},
            ])
            await session.commit()

        async with session_factory() as session:
            rows = await repo.get_final_transcript(session, meeting_id)
        return rows

    rows = asyncio.run(scenario())
    assert rows == [("Anda", "Selamat pagi"), ("Speaker 1", "Mari mulai")]


def test_get_summary_returns_none_when_absent():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            return await repo.get_summary(session, meeting_id)

    assert asyncio.run(scenario()) is None


def test_find_abandoned_meetings_matches_new_statuses():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            m1 = await repo.create_meeting(session, "A", None)
            await repo.mark_meeting_status(session, m1.id, "transcribing")
            m2 = await repo.create_meeting(session, "B", None)
            await repo.mark_meeting_status(session, m2.id, "summarizing")
            m3 = await repo.create_meeting(session, "C", None)
            await repo.mark_meeting_status(session, m3.id, "recorded")
            await session.commit()
            ids = {m1.id, m2.id}

        async with session_factory() as session:
            abandoned = await repo.find_abandoned_meetings(session)
        return ids, {m.id for m in abandoned}

    expected, found = asyncio.run(scenario())
    assert found == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/storage -v`
Expected: FAIL — `Meeting` has no `error_message`/`failed_stage`, `repo.mark_meeting_failed`/`has_final_segments`/`get_final_transcript`/`get_summary` don't exist, `stop_recording` still sets `"processing"`, `find_abandoned_meetings` still matches `"processing"`.

- [ ] **Step 3: Implement**

In `app/storage/models.py`, inside the `Meeting` class, right after `recording_dir`:

```python
    error_message: Mapped[str | None] = mapped_column(default=None)
    failed_stage: Mapped[str | None] = mapped_column(default=None)
```

In `app/storage/repository.py`, change `stop_recording`:

```python
async def stop_recording(session: AsyncSession, meeting_id: int) -> None:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} not found")
    meeting.status = "recorded"
    meeting.end_time = _utcnow()
```

Change `find_abandoned_meetings`:

```python
async def find_abandoned_meetings(session: AsyncSession) -> list[Meeting]:
    """A meeting stuck in recording/transcribing/summarizing never reached a
    terminal or resting status (recorded/transcribed/completed/failed) -- the
    only way that happens is the app dying mid-action, e.g. a crash."""
    result = await session.execute(
        select(Meeting).where(Meeting.status.in_(["recording", "transcribing", "summarizing"]))
    )
    return list(result.scalars().all())
```

Add at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/storage -v`
Expected: PASS (all tests including the pre-existing ones)

- [ ] **Step 5: Apply the same schema change to the live Postgres database**

Run:

```bash
./.venv/Scripts/python.exe -c "
import asyncio
from app.config import get_settings
from app.storage.db import make_engine
from sqlalchemy import text

async def main():
    settings = get_settings()
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text('ALTER TABLE meetings ADD COLUMN IF NOT EXISTS error_message VARCHAR'))
        await conn.execute(text('ALTER TABLE meetings ADD COLUMN IF NOT EXISTS failed_stage VARCHAR'))
    print('OK: error_message + failed_stage columns ensured on meetings table')
    await engine.dispose()

asyncio.run(main())
"
```

Expected output: `OK: error_message + failed_stage columns ensured on meetings table`

- [ ] **Step 6: Commit**

```bash
git add app/storage/models.py app/storage/repository.py tests/storage/test_models.py tests/storage/test_repository.py
git commit -m "feat(fase3): add meeting failure fields and granular-status repository queries"
```

---

## Task 2: `transcribe_and_diarize()` pipeline function

**Files:**
- Create: `app/pipeline/transcribe.py`
- Test: `tests/pipeline/test_transcribe.py`

**Interfaces:**
- Consumes: `repo.mark_meeting_status`, `repo.mark_meeting_failed`, `repo.get_or_create_speaker`, `repo.clear_draft_segments`, `repo.save_transcript_segments` (Task 1 + existing), `merge_segments` (`app/pipeline/merge.py`, unchanged)
- Produces: `async def transcribe_and_diarize(session_factory, meeting_id: int, mic_wav: Path, speaker_wav: Path, transcriber, diarizer) -> None` — sets status `"transcribing"` immediately, then `"transcribed"` on success or `"failed"` (`failed_stage="transcribe"`) on any exception (re-raised after marking).

- [ ] **Step 1: Write the failing tests**

Create `tests/pipeline/test_transcribe.py`:

```python
import asyncio
from datetime import datetime

from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment
from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.storage.models import TranscriptSegment
from app.pipeline.transcribe import transcribe_and_diarize


class RoutingFakeTranscriber:
    def __init__(self, by_filename):
        self._by_filename = by_filename

    def transcribe(self, wav_path, language="id"):
        return self._by_filename[wav_path.name]


class FakeDiarizer:
    def __init__(self, labels):
        self._labels = labels

    def diarize(self, wav_path):
        return self._labels


class ExplodingTranscriber:
    def transcribe(self, wav_path, language="id"):
        raise RuntimeError("CUDA out of memory")


def test_transcribe_and_diarize_saves_final_segments_and_marks_transcribed(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await repo.mark_meeting_status(session, meeting.id, "recorded")
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        transcriber = RoutingFakeTranscriber({
            "mic.wav": [TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")],
            "speaker.wav": [TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")],
        })
        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])

        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, diarizer)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            from sqlalchemy import select
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return meetings, segments

    meetings, segments = asyncio.run(scenario())
    assert meetings[0].status == "transcribed"
    assert {s.text for s in segments} == {"Selamat pagi", "Mari kita mulai"}
    assert all(s.is_final for s in segments)


def test_transcribe_and_diarize_marks_failed_on_transcriber_error(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        exception_raised = None
        try:
            await transcribe_and_diarize(
                session_factory, meeting_id, mic_wav, speaker_wav,
                ExplodingTranscriber(), FakeDiarizer([]),
            )
        except RuntimeError as e:
            exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return exception_raised, meetings

    exception_raised, meetings = asyncio.run(scenario())
    assert exception_raised is not None
    assert "CUDA out of memory" in str(exception_raised)
    assert meetings[0].status == "failed"
    assert meetings[0].failed_stage == "transcribe"
    assert "CUDA out of memory" in meetings[0].error_message


def test_transcribe_and_diarize_clears_existing_drafts_first(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 400, "text": "draft belum sempat dihapus", "is_final": False},
            ])
            await session.commit()

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()

        transcriber = RoutingFakeTranscriber({
            "mic.wav": [TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")],
            "speaker.wav": [],
        })
        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, FakeDiarizer([]))

        async with session_factory() as session:
            from sqlalchemy import select
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return segments

    segments = asyncio.run(scenario())
    texts = {s.text for s in segments}
    assert "draft belum sempat dihapus" not in texts
    assert "Selamat pagi" in texts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/pipeline/test_transcribe.py -v`
Expected: FAIL — `app.pipeline.transcribe` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `app/pipeline/transcribe.py`:

```python
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
            await repo.clear_draft_segments(session, meeting_id)
            await repo.save_transcript_segments(session, segment_rows)
            await repo.mark_meeting_status(session, meeting_id, "transcribed")
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            await repo.mark_meeting_failed(session, meeting_id, "transcribe", str(exc))
            await session.commit()
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/pipeline/test_transcribe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/transcribe.py tests/pipeline/test_transcribe.py
git commit -m "feat(fase3): add transcribe_and_diarize as an independently-triggerable pipeline stage"
```

---

## Task 3: `summarize_and_export()` pipeline function, remove `finalize.py`

**Files:**
- Create: `app/pipeline/summarize.py`
- Delete: `app/pipeline/finalize.py`
- Delete: `tests/pipeline/test_finalize.py`
- Test: `tests/pipeline/test_summarize.py`

**Interfaces:**
- Consumes: `repo.get_final_transcript`, `repo.save_summary`, `repo.mark_meeting_status`, `repo.mark_meeting_failed` (Task 1), `export_mom_docx` (`app/summarization/docx_export.py`, unchanged)
- Produces: `async def summarize_and_export(session_factory, meeting_id: int, meeting_title: str, meeting_date: datetime, docx_output_path: Path, summarizer) -> Summary` — sets status `"summarizing"` immediately, `"completed"` on success, `"failed"` (`failed_stage="summarize"`) on any exception (re-raised after marking).

- [ ] **Step 1: Write the failing tests**

Create `tests/pipeline/test_summarize.py`:

```python
import asyncio
from datetime import datetime

from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.summarization.groq_client import MomResult
from app.pipeline.summarize import summarize_and_export


class FakeSummarizer:
    model = "llama-3.3-70b-versatile"

    def summarize(self, meeting_title, transcript_text):
        assert "Anda" in transcript_text
        return MomResult(
            minute_by_minute=[{"time": "00:00", "point": "Mulai"}],
            decisions=["Lanjut"], action_items=[], detailed_notes="Catatan.",
        )


class FailingSummarizer:
    model = "llama-3.3-70b-versatile"

    def summarize(self, meeting_title, transcript_text):
        raise RuntimeError("Groq timeout")


async def _seed_transcribed_meeting(session_factory, title="Rapat Uji"):
    async with session_factory() as session:
        meeting = await repo.create_meeting(session, title, None)
        await session.commit()
        meeting_id = meeting.id
        await repo.save_transcript_segments(session, [
            {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
             "start_ms": 0, "end_ms": 500, "text": "Selamat pagi"},
        ])
        await repo.mark_meeting_status(session, meeting_id, "transcribed")
        await session.commit()
    return meeting_id


def test_summarize_and_export_reads_transcript_from_db_and_completes(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        meeting_id = await _seed_transcribed_meeting(session_factory)

        docx_path = tmp_path / "mom.docx"
        summary = await summarize_and_export(
            session_factory, meeting_id, "Rapat Uji", datetime(2026, 7, 31, 9, 0),
            docx_path, FakeSummarizer(),
        )

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return summary, meetings, docx_path.exists()

    summary, meetings, docx_exists = asyncio.run(scenario())
    assert summary.status == "ready"
    assert meetings[0].status == "completed"
    assert docx_exists is True


def test_summarize_and_export_marks_failed_on_summarizer_error(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        meeting_id = await _seed_transcribed_meeting(session_factory)

        exception_raised = None
        try:
            await summarize_and_export(
                session_factory, meeting_id, "Rapat Uji", datetime(2026, 7, 31, 9, 0),
                tmp_path / "mom.docx", FailingSummarizer(),
            )
        except RuntimeError as e:
            exception_raised = e

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            segments = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return exception_raised, meetings, segments

    exception_raised, meetings, segments = asyncio.run(scenario())
    assert exception_raised is not None
    assert meetings[0].status == "failed"
    assert meetings[0].failed_stage == "summarize"
    assert "Groq timeout" in meetings[0].error_message
    # the transcript from the earlier transcribe stage must survive intact
    assert len(segments) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/pipeline/test_summarize.py -v`
Expected: FAIL — `app.pipeline.summarize` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `app/pipeline/summarize.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/pipeline/test_summarize.py -v`
Expected: PASS

- [ ] **Step 5: Delete the now-superseded finalize module and its test**

```bash
git rm app/pipeline/finalize.py tests/pipeline/test_finalize.py
```

- [ ] **Step 6: Run the full suite to confirm nothing else references `finalize.py`**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: FAIL at collection with `ModuleNotFoundError`/`ImportError` for `app.pipeline.finalize` in `app/main.py` and `app/ui/controller.py` — **expected at this point in the plan**, Task 8 fixes `main.py`'s import. If any *other* file unexpectedly imports `app.pipeline.finalize`, note it here and fix it now (it means Task 8's plan missed a reference).

- [ ] **Step 7: Commit**

```bash
git add app/pipeline/summarize.py tests/pipeline/test_summarize.py
git commit -m "feat(fase3): add summarize_and_export, remove superseded finalize_meeting"
```

---

## Task 4: Rewrite `recovery.py` to reset status instead of auto-processing

**Files:**
- Modify: `app/pipeline/recovery.py` (full rewrite)
- Test: `tests/pipeline/test_recovery.py` (full rewrite)

**Interfaces:**
- Consumes: `repo.find_abandoned_meetings`, `repo.has_final_segments`, `repo.get_summary`, `repo.mark_meeting_status`, `repo.mark_meeting_failed` (Task 1)
- Produces: `async def recover_abandoned_meetings(session_factory) -> list[int]` — **signature change**: no longer takes a `finalize_fn` parameter. Returns the ids it touched.
  - `status == "recording"` → `"recorded"` if `recording_dir` + both WAV files exist, else `"failed"` (`failed_stage="transcribe"`)
  - `status == "transcribing"` → `"transcribed"` if `has_final_segments()` is true, else `"recorded"` (safe to just re-click Transkrip)
  - `status == "summarizing"` → `"completed"` if a `Summary` with `status == "ready"` exists, else `"transcribed"` (the transcript from the earlier stage is untouched; safe to re-click Ringkasan)

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/pipeline/test_recovery.py`:

```python
import asyncio

from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.pipeline.recovery import recover_abandoned_meetings


def test_no_abandoned_meetings_returns_empty_list():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        return await recover_abandoned_meetings(session_factory)

    assert asyncio.run(scenario()) == []


def test_recording_with_wav_files_resets_to_recorded(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        meeting_dir = tmp_path / "abc123"
        meeting_dir.mkdir()
        (meeting_dir / "mic.wav").write_bytes(b"x")
        (meeting_dir / "speaker.wav").write_bytes(b"x")

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Terputus", None, recording_dir=str(meeting_dir))
            await repo.start_recording(session, meeting.id)
            await session.commit()
            meeting_id = meeting.id

        recovered = await recover_abandoned_meetings(session_factory)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meeting_id, recovered, meetings

    meeting_id, recovered, meetings = asyncio.run(scenario())
    assert recovered == [meeting_id]
    assert meetings[0].status == "recorded"


def test_recording_without_wav_files_marked_failed(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Lama", None)
            await repo.start_recording(session, meeting.id)
            await session.commit()

        await recover_abandoned_meetings(session_factory)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "failed"
    assert meetings[0].failed_stage == "transcribe"


def test_transcribing_with_final_segments_resets_to_transcribed():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "Selamat pagi"},
            ])
            await repo.mark_meeting_status(session, meeting_id, "transcribing")
            await session.commit()

        await recover_abandoned_meetings(session_factory)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "transcribed"


def test_transcribing_without_final_segments_resets_to_recorded():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await repo.mark_meeting_status(session, meeting.id, "transcribing")
            await session.commit()

        await recover_abandoned_meetings(session_factory)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "recorded"


def test_summarizing_with_ready_summary_resets_to_completed():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id
            await repo.save_summary(
                session, meeting_id, mom_json="{}", docx_path="./x.docx",
                groq_model="llama-3.3-70b-versatile", status="ready",
            )
            await repo.mark_meeting_status(session, meeting_id, "summarizing")
            await session.commit()

        await recover_abandoned_meetings(session_factory)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "completed"


def test_summarizing_without_ready_summary_resets_to_transcribed():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await repo.mark_meeting_status(session, meeting.id, "summarizing")
            await session.commit()

        await recover_abandoned_meetings(session_factory)

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return meetings

    meetings = asyncio.run(scenario())
    assert meetings[0].status == "transcribed"


def test_recorded_and_completed_meetings_are_left_untouched():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            m1 = await repo.create_meeting(session, "A", None)
            await repo.mark_meeting_status(session, m1.id, "recorded")
            m2 = await repo.create_meeting(session, "B", None)
            await repo.mark_meeting_status(session, m2.id, "completed")
            await session.commit()

        return await recover_abandoned_meetings(session_factory)

    assert asyncio.run(scenario()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/pipeline/test_recovery.py -v`
Expected: FAIL — old `recover_abandoned_meetings(session_factory, finalize_fn)` signature/behavior doesn't match.

- [ ] **Step 3: Implement**

Replace the entire contents of `app/pipeline/recovery.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/pipeline/test_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/recovery.py tests/pipeline/test_recovery.py
git commit -m "refactor(fase3): recovery resets meeting status instead of re-running the pipeline"
```

---

## Task 5: `RecorderController` — simplify Stop, add history actions

**Files:**
- Modify: `app/ui/controller.py` (full rewrite of the class)
- Modify: `tests/ui/test_controller.py` (rewrite tests that used `finalize_fn`; keep tests unrelated to it)

**Interfaces:**
- Consumes: `transcribe_and_diarize` (Task 2), `summarize_and_export` (Task 3), `repo.list_meetings`, `repo.get_final_transcript`, `repo.get_summary` (Task 1)
- Produces (constructor signature change): `RecorderController(session_factory, recorder_factory, transcribe_fn, summarize_fn, recordings_dir, live_session_factory=None)` — **`finalize_fn` param removed, replaced by `transcribe_fn` and `summarize_fn`**
  - `transcribe_fn` shape: `async def transcribe_fn(meeting_id: int, mic_wav: Path, speaker_wav: Path) -> None`
  - `summarize_fn` shape: `async def summarize_fn(meeting_id: int, meeting_title: str, meeting_date: datetime) -> None`
- Produces: `controller.stop_meeting()` — now ends at `state == "idle"` (not `"processing"`/`"done"`); DB status ends at `"recorded"`, not `"completed"`. No longer touches `last_docx_path` or `processing_step` (both removed).
- Produces: `controller.run_transcribe(meeting_id: int) -> None` (blocking; call from a background thread)
- Produces: `controller.run_summarize(meeting_id: int) -> None` (blocking; call from a background thread)
- Produces: `controller.retry(meeting_id: int) -> None` (blocking; reads `failed_stage` from DB and calls the right one)
- Produces: `controller.list_meetings() -> list[Meeting]` (blocking, cheap)
- Produces: `controller.get_transcript(meeting_id: int) -> list[tuple[str, str]]` (blocking)
- Produces: `controller.get_docx_path(meeting_id: int) -> str | None` (blocking)

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/ui/test_controller.py`:

```python
import asyncio
import wave
from pathlib import Path

from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.ui.controller import RecorderController


def _write_silent_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((0).to_bytes(2, "little", signed=True) * 160)


class FakeRecorder:
    def __init__(self, mic_path, speaker_path):
        self.mic_path = mic_path
        self.speaker_path = speaker_path
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        _write_silent_wav(self.mic_path)
        _write_silent_wav(self.speaker_path)

    def stop(self):
        self.stopped = True
        return self.mic_path, self.speaker_path


class BrokenRecorder:
    def __init__(self, mic_path, speaker_path):
        pass

    def start(self):
        raise OSError("no default input device")


async def _noop_transcribe_fn(meeting_id, mic_wav, speaker_wav):
    pass


async def _noop_summarize_fn(meeting_id, meeting_title, meeting_date):
    pass


def _make_controller(tmp_path, session_factory, transcribe_fn=_noop_transcribe_fn,
                      summarize_fn=_noop_summarize_fn, recorder_cls=FakeRecorder,
                      live_session_factory=None):
    return RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: recorder_cls(mic, speaker),
        transcribe_fn=transcribe_fn,
        summarize_fn=summarize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
    )


def test_start_then_stop_meeting_ends_idle_with_status_recorded(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory)

    meeting_id = controller.start_meeting("Rapat Harian")
    assert controller.state == "recording"

    controller.stop_meeting()
    assert controller.state == "idle"

    async def _get():
        async with session_factory() as session:
            from app.storage.models import Meeting
            return await session.get(Meeting, meeting_id)

    meeting = asyncio.run(_get())
    assert meeting.status == "recorded"


def test_start_meeting_sets_error_state_when_device_missing(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory, recorder_cls=BrokenRecorder)

    try:
        controller.start_meeting("Rapat Gagal")
        assert False, "expected OSError to propagate"
    except OSError:
        pass

    assert controller.state == "error"
    assert "mic/speaker" in controller.error_message


def test_stop_meeting_raises_when_no_active_recording(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory)

    try:
        controller.stop_meeting()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "no meeting is currently being recorded" in str(e)


def test_run_transcribe_calls_transcribe_fn_with_recording_paths(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    calls = []

    async def spy_transcribe_fn(meeting_id, mic_wav, speaker_wav):
        calls.append((meeting_id, mic_wav, speaker_wav))

    controller = _make_controller(tmp_path, session_factory, transcribe_fn=spy_transcribe_fn)

    async def _seed():
        recording_dir = tmp_path / "abc"
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None, recording_dir=str(recording_dir))
            await session.commit()
            return meeting.id, recording_dir

    meeting_id, recording_dir = asyncio.run(_seed())

    controller.run_transcribe(meeting_id)

    assert len(calls) == 1
    called_id, mic_wav, speaker_wav = calls[0]
    assert called_id == meeting_id
    assert mic_wav == recording_dir / "mic.wav"
    assert speaker_wav == recording_dir / "speaker.wav"


def test_run_summarize_calls_summarize_fn_with_title_and_date(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    calls = []

    async def spy_summarize_fn(meeting_id, meeting_title, meeting_date):
        calls.append((meeting_id, meeting_title, meeting_date))

    controller = _make_controller(tmp_path, session_factory, summarize_fn=spy_summarize_fn)

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Penting", None)
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())

    controller.run_summarize(meeting_id)

    assert len(calls) == 1
    assert calls[0][0] == meeting_id
    assert calls[0][1] == "Rapat Penting"


def test_retry_calls_transcribe_fn_when_failed_stage_is_transcribe(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    transcribe_calls = []
    summarize_calls = []

    async def spy_transcribe_fn(meeting_id, mic_wav, speaker_wav):
        transcribe_calls.append(meeting_id)

    async def spy_summarize_fn(meeting_id, meeting_title, meeting_date):
        summarize_calls.append(meeting_id)

    controller = _make_controller(tmp_path, session_factory, transcribe_fn=spy_transcribe_fn, summarize_fn=spy_summarize_fn)

    async def _seed():
        recording_dir = tmp_path / "abc"
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None, recording_dir=str(recording_dir))
            await session.commit()
            await repo.mark_meeting_failed(session, meeting.id, "transcribe", "boom")
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())

    controller.retry(meeting_id)

    assert transcribe_calls == [meeting_id]
    assert summarize_calls == []


def test_retry_calls_summarize_fn_when_failed_stage_is_summarize(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    transcribe_calls = []
    summarize_calls = []

    async def spy_transcribe_fn(meeting_id, mic_wav, speaker_wav):
        transcribe_calls.append(meeting_id)

    async def spy_summarize_fn(meeting_id, meeting_title, meeting_date):
        summarize_calls.append(meeting_id)

    controller = _make_controller(tmp_path, session_factory, transcribe_fn=spy_transcribe_fn, summarize_fn=spy_summarize_fn)

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            await repo.mark_meeting_failed(session, meeting.id, "summarize", "boom")
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())

    controller.retry(meeting_id)

    assert summarize_calls == [meeting_id]
    assert transcribe_calls == []


def test_list_meetings_returns_created_meetings(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory)

    async def _seed():
        async with session_factory() as session:
            await repo.create_meeting(session, "Rapat A", None)
            await repo.create_meeting(session, "Rapat B", None)
            await session.commit()

    asyncio.run(_seed())

    titles = {m.title for m in controller.list_meetings()}
    assert titles == {"Rapat A", "Rapat B"}


def test_get_transcript_and_get_docx_path(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory)

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            meeting_id = meeting.id
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "Halo"},
            ])
            await repo.save_summary(
                session, meeting_id, mom_json="{}", docx_path="C:/x/mom.docx",
                groq_model="llama-3.3-70b-versatile", status="ready",
            )
            await session.commit()
            return meeting_id

    meeting_id = asyncio.run(_seed())

    assert controller.get_transcript(meeting_id) == [("Anda", "Halo")]
    assert controller.get_docx_path(meeting_id) == "C:/x/mom.docx"


def test_get_docx_path_returns_none_when_no_summary(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory)

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())
    assert controller.get_docx_path(meeting_id) is None
```

Append the live-session tests below to the same file (unaffected by the `finalize_fn`→`transcribe_fn`/`summarize_fn` rename in spirit, just adapted to the new `_make_controller` helper defined above instead of building `RecorderController(...)` inline with `finalize_fn=...`):

```python
class FakeLiveSession:
    def __init__(self, mic_wav_path, speaker_wav_path, scratch_dir):
        self.mic_wav_path = mic_wav_path
        self.speaker_wav_path = speaker_wav_path
        self.scratch_dir = scratch_dir
        self.started = False
        self.stopped = False
        self.meeting_id = None

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class BrokenStopLiveSession(FakeLiveSession):
    def stop(self):
        self.stopped = True
        raise RuntimeError("live session stop hung/failed")


class BrokenRecorderStartThenDB:
    """Recorder that starts successfully but simulates a DB write failure."""
    def __init__(self, mic_path, speaker_path):
        self.mic_path = mic_path
        self.speaker_path = speaker_path
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        _write_silent_wav(self.mic_path)
        _write_silent_wav(self.speaker_path)

    def stop(self):
        self.stopped = True
        return self.mic_path, self.speaker_path


class FailingSessionFactoryWrapper:
    """Wraps the real session factory but makes commit fail."""
    def __init__(self, real_factory):
        self._real_factory = real_factory

    def __call__(self):
        return self._WrappedContext(self._real_factory)

    class _WrappedContext:
        def __init__(self, real_factory):
            self.real_factory = real_factory
            self.real_session = None

        async def __aenter__(self):
            self.real_session = await self.real_factory().__aenter__()
            return self

        async def __aexit__(self, *args):
            if self.real_session:
                await self.real_session.__aexit__(*args)

        def add(self, obj):
            self.real_session.add(obj)

        async def flush(self):
            await self.real_session.flush()

        async def get(self, model_class, pk):
            return await self.real_session.get(model_class, pk)

        async def commit(self):
            raise RuntimeError("Simulated DB write failure")


def test_start_meeting_starts_live_session_when_factory_provided(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    controller = _make_controller(tmp_path, session_factory, live_session_factory=live_session_factory)

    meeting_id = controller.start_meeting("Rapat Live")
    assert len(created_sessions) == 1
    assert created_sessions[0].started is True
    assert created_sessions[0].meeting_id == meeting_id

    controller.stop_meeting()
    assert created_sessions[0].stopped is True


def _live_session_test_controller(tmp_path, live_session_cls, recorder_cls, session_factory):
    created = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = live_session_cls(mic_wav_path, speaker_wav_path, scratch_dir)
        created.append(live_session)
        return live_session

    controller = _make_controller(tmp_path, session_factory, recorder_cls=recorder_cls, live_session_factory=live_session_factory)
    return controller, created


def test_failing_live_session_stop_does_not_block_stop_meeting(tmp_path):
    """I3: a slow or broken live_session.stop() must never stop the recorder
    from being stopped or the meeting from being saved."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    controller, created = _live_session_test_controller(tmp_path, BrokenStopLiveSession, FakeRecorder, session_factory)

    controller.start_meeting("Rapat Live Stop Gagal")
    controller.stop_meeting()

    assert created[0].stopped is True
    assert controller.state == "idle"


def test_failing_live_session_stop_does_not_mask_recorder_start_error(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    controller, created = _live_session_test_controller(tmp_path, BrokenStopLiveSession, BrokenRecorder, session_factory)

    try:
        controller.start_meeting("Rapat Recorder Fail")
        assert False, "expected the ORIGINAL OSError from the recorder to propagate"
    except OSError:
        pass

    assert created[0].stopped is True
    assert controller.state == "error"
    assert "mic/speaker" in controller.error_message


def test_failing_live_session_stop_does_not_mask_db_error(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    real_session_factory = make_session_factory(engine)

    controller, created = _live_session_test_controller(
        tmp_path, BrokenStopLiveSession, BrokenRecorderStartThenDB,
        FailingSessionFactoryWrapper(real_session_factory),
    )

    try:
        controller.start_meeting("Rapat DB Fail")
        assert False, "expected the ORIGINAL RuntimeError from the DB to propagate"
    except RuntimeError as e:
        assert "Simulated DB write failure" in str(e)

    assert created[0].stopped is True
    assert "Gagal menyimpan data meeting" in controller.error_message


def test_start_meeting_without_live_session_factory_behaves_like_fase1(tmp_path):
    """live_session_factory defaults to None: no live session, no behavior change."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory)

    controller.start_meeting("Rapat Tanpa Live")
    controller.stop_meeting()
    assert controller.state == "idle"


def test_live_session_construction_failure_does_not_block_recording(tmp_path):
    """spec §5: live preview must never prevent the recording itself from starting."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    def broken_live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        raise RuntimeError("silero-vad model download failed")

    controller = _make_controller(tmp_path, session_factory, live_session_factory=broken_live_session_factory)

    controller.start_meeting("Rapat Live Gagal")
    assert controller.state == "recording"


def test_live_session_stopped_when_db_write_fails_after_it_started(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    real_session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    controller = _make_controller(
        tmp_path, FailingSessionFactoryWrapper(real_session_factory),
        recorder_cls=BrokenRecorderStartThenDB, live_session_factory=live_session_factory,
    )

    try:
        controller.start_meeting("Rapat DB Fail Live")
        assert False, "expected RuntimeError from DB"
    except RuntimeError:
        pass

    assert len(created_sessions) == 1
    assert created_sessions[0].started is True
    assert created_sessions[0].stopped is True


def test_live_session_stopped_when_recorder_start_fails(tmp_path):
    """spec §1: if recorder.start() fails AFTER a live session successfully
    started, the live session must be stopped to avoid resource leak."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    controller = _make_controller(tmp_path, session_factory, recorder_cls=BrokenRecorder, live_session_factory=live_session_factory)

    try:
        controller.start_meeting("Rapat Recorder Fail")
        assert False, "expected OSError from recorder"
    except OSError:
        pass

    assert len(created_sessions) == 1
    assert created_sessions[0].started is True
    assert created_sessions[0].stopped is True
```

The plan's Step 4 test run below must include all of these passing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/ui/test_controller.py -v`
Expected: FAIL — `RecorderController.__init__()` doesn't accept `transcribe_fn`/`summarize_fn` yet, `run_transcribe`/`run_summarize`/`retry`/`list_meetings`/`get_transcript`/`get_docx_path` don't exist yet.

- [ ] **Step 3: Implement**

Replace the entire contents of `app/ui/controller.py`:

```python
import asyncio
import logging
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from app.storage import repository as repo
from app.storage.models import Meeting

logger = logging.getLogger(__name__)


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)


class RecorderController:
    def __init__(
        self,
        session_factory,
        recorder_factory: Callable,
        transcribe_fn: Callable[..., Awaitable],
        summarize_fn: Callable[..., Awaitable],
        recordings_dir: Path,
        live_session_factory: Callable[[Path, Path, Path], object] | None = None,
    ):
        self._session_factory = session_factory
        self._recorder_factory = recorder_factory
        self._transcribe_fn = transcribe_fn
        self._summarize_fn = summarize_fn
        self._recordings_dir = recordings_dir
        self._live_session_factory = live_session_factory
        self.state = "idle"
        self.error_message: str | None = None
        self._meeting_id: int | None = None
        self._meeting_title: str | None = None
        self._recorder = None
        self._live_session = None

    def _stop_live_session(self) -> None:
        """Stopping live preview must never mask the real error or block the
        recorder from being stopped -- it is best-effort, spec §5."""
        if self._live_session is None:
            return
        try:
            self._live_session.stop()
        except Exception as exc:
            logger.warning("live session failed to stop cleanly: %s", exc)
        finally:
            self._live_session = None

    def start_meeting(self, title: str) -> int:
        session_dirname = uuid.uuid4().hex
        meeting_dir = self._recordings_dir / session_dirname
        mic_path = meeting_dir / "mic.wav"
        speaker_path = meeting_dir / "speaker.wav"

        # Live session must start BEFORE the recorder is constructed: the real
        # recorder_factory (wired in main.py) reads the live session's queues
        # at construction time, so those queues must already exist by the time
        # recorder_factory(...) runs below. Do not reorder this.
        self._live_session = None
        if self._live_session_factory is not None:
            try:
                self._live_session = self._live_session_factory(mic_path, speaker_path, meeting_dir / "live_scratch")
                self._live_session.start()
            except Exception as exc:
                logger.warning("live preview unavailable this meeting: %s", exc)
                self._live_session = None

        recorder = self._recorder_factory(mic_path, speaker_path)

        try:
            recorder.start()
        except Exception as exc:
            self._stop_live_session()
            self.error_message = f"Gagal memulai rekam (cek perangkat mic/speaker): {exc}"
            self.state = "error"
            raise

        async def _create():
            async with self._session_factory() as session:
                meeting = await repo.create_meeting(
                    session, title, datetime.now(timezone.utc), recording_dir=str(meeting_dir),
                )
                await repo.start_recording(session, meeting.id)
                await session.commit()
                return meeting.id

        try:
            meeting_id = asyncio.run(_create())
        except Exception as exc:
            recorder.stop()
            self._stop_live_session()
            self.error_message = f"Gagal menyimpan data meeting: {exc}"
            self.state = "error"
            raise

        if self._live_session is not None:
            # Only now does the meeting row exist; before this the live session
            # keeps its drafts out of the DB (see LiveSession.meeting_id).
            self._live_session.meeting_id = meeting_id

        self._meeting_id = meeting_id
        self._meeting_title = title
        self._recorder = recorder
        self.state = "recording"
        return meeting_id

    def stop_meeting(self) -> None:
        """Stop only saves the recording and marks it "recorded" -- Fase 3
        moved transcription/summarization to manual, per-meeting actions
        (run_transcribe/run_summarize) triggered from the history view, so
        this never blocks starting the next meeting."""
        if self._recorder is None:
            raise RuntimeError("cannot stop: no meeting is currently being recorded")

        self._stop_live_session()

        mic_path, speaker_path = self._recorder.stop()

        async def _save():
            async with self._session_factory() as session:
                await repo.stop_recording(session, self._meeting_id)
                await repo.save_recording_file(
                    session, self._meeting_id, str(mic_path), "mic", _wav_duration_ms(mic_path)
                )
                await repo.save_recording_file(
                    session, self._meeting_id, str(speaker_path), "speaker", _wav_duration_ms(speaker_path)
                )
                await session.commit()

        try:
            asyncio.run(_save())
            self.state = "idle"
            self._recorder = None
        except Exception as exc:
            self.error_message = f"Gagal menyimpan hasil rekaman: {exc}"
            self.state = "error"
            raise

    def run_transcribe(self, meeting_id: int) -> None:
        """Blocking -- call from a background thread (the UI layer owns
        threading, matching start_meeting/stop_meeting's existing pattern)."""
        async def _run():
            async with self._session_factory() as session:
                meeting = await session.get(Meeting, meeting_id)
                if meeting is None:
                    raise ValueError(f"Meeting {meeting_id} not found")
                mic_wav = Path(meeting.recording_dir) / "mic.wav"
                speaker_wav = Path(meeting.recording_dir) / "speaker.wav"
            await self._transcribe_fn(meeting_id=meeting_id, mic_wav=mic_wav, speaker_wav=speaker_wav)

        asyncio.run(_run())

    def run_summarize(self, meeting_id: int) -> None:
        """Blocking -- call from a background thread."""
        async def _run():
            async with self._session_factory() as session:
                meeting = await session.get(Meeting, meeting_id)
                if meeting is None:
                    raise ValueError(f"Meeting {meeting_id} not found")
                title = meeting.title
                date = meeting.start_time or meeting.created_at
            await self._summarize_fn(meeting_id=meeting_id, meeting_title=title, meeting_date=date)

        asyncio.run(_run())

    def retry(self, meeting_id: int) -> None:
        """Blocking -- re-runs whichever stage failed."""
        async def _get_stage():
            async with self._session_factory() as session:
                meeting = await session.get(Meeting, meeting_id)
                if meeting is None:
                    raise ValueError(f"Meeting {meeting_id} not found")
                return meeting.failed_stage

        stage = asyncio.run(_get_stage())
        if stage == "summarize":
            self.run_summarize(meeting_id)
        else:
            self.run_transcribe(meeting_id)

    def list_meetings(self) -> list[Meeting]:
        async def _list():
            async with self._session_factory() as session:
                return await repo.list_meetings(session)

        return asyncio.run(_list())

    def get_transcript(self, meeting_id: int) -> list[tuple[str, str]]:
        async def _get():
            async with self._session_factory() as session:
                return await repo.get_final_transcript(session, meeting_id)

        return asyncio.run(_get())

    def get_docx_path(self, meeting_id: int) -> str | None:
        async def _get():
            async with self._session_factory() as session:
                summary = await repo.get_summary(session, meeting_id)
                return summary.docx_path if summary else None

        return asyncio.run(_get())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/ui/test_controller.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/controller.py tests/ui/test_controller.py
git commit -m "feat(fase3): controller -- Stop only saves the recording; add per-meeting transcribe/summarize/retry actions"
```

---

## Task 6: `HistoryView` widget

**Files:**
- Create: `app/ui/history_view.py`
- Test: `tests/ui/test_history_view.py`

**Interfaces:**
- Consumes: `controller.list_meetings()`, `controller.run_transcribe()`, `controller.run_summarize()`, `controller.retry()`, `controller.get_transcript()`, `controller.get_docx_path()` (Task 5)
- Produces: `class HistoryView(tk.Frame)` — constructed as `HistoryView(parent, controller)`. Public methods used by tests/other code: `refresh()` (re-queries `list_meetings()` and re-renders the Treeview + action panel for the current selection).

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_history_view.py`:

```python
import tkinter as tk
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ui.history_view import HistoryView


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        root.update()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


def _meeting(id, title, status, error_message=None, failed_stage=None):
    return SimpleNamespace(
        id=id, title=title, status=status,
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        error_message=error_message, failed_stage=failed_stage,
    )


class FakeController:
    def __init__(self, meetings):
        self._meetings = meetings
        self.transcribe_calls = []
        self.summarize_calls = []
        self.retry_calls = []
        self.download_calls = []
        self.transcript_by_id = {}

    def list_meetings(self):
        return self._meetings

    def run_transcribe(self, meeting_id):
        self.transcribe_calls.append(meeting_id)

    def run_summarize(self, meeting_id):
        self.summarize_calls.append(meeting_id)

    def retry(self, meeting_id):
        self.retry_calls.append(meeting_id)

    def get_transcript(self, meeting_id):
        return self.transcript_by_id.get(meeting_id, [])

    def get_docx_path(self, meeting_id):
        self.download_calls.append(meeting_id)
        return "C:/recordings/1/mom.docx"


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_refresh_populates_treeview_rows():
    root = tk.Tk()
    controller = FakeController([
        _meeting(1, "Rapat A", "recorded"),
        _meeting(2, "Rapat B", "completed"),
    ])
    view = HistoryView(root, controller)

    children = view._tree.get_children()
    assert len(children) == 2
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_recorded_meeting_shows_transcribe_button():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)

    view._tree.selection_set("1")
    view._on_select()

    assert str(view._transcribe_button.winfo_manager()) == "pack"
    assert str(view._summarize_button.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_transcribed_meeting_shows_summarize_and_view_transcript_buttons():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "transcribed")])
    view = HistoryView(root, controller)

    view._tree.selection_set("1")
    view._on_select()

    assert str(view._summarize_button.winfo_manager()) == "pack"
    assert str(view._view_transcript_button.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_failed_meeting_shows_retry_button_and_error_message():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "failed", error_message="Groq timeout")])
    view = HistoryView(root, controller)

    view._tree.selection_set("1")
    view._on_select()

    assert str(view._retry_button.winfo_manager()) == "pack"
    assert "Groq timeout" in view._status_label.cget("text")
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_transcribe_button_calls_controller_run_transcribe():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_transcribe()

    assert controller.transcribe_calls == [1]
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_view_transcript_renders_lines_in_transcript_view():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "transcribed")])
    controller.transcript_by_id[1] = [("Anda", "Selamat pagi"), ("Speaker 1", "Mari mulai")]
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_view_transcript()

    content = view._transcript_view.get("1.0", "end")
    assert "Anda: Selamat pagi" in content
    assert "Speaker 1: Mari mulai" in content
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_download_button_calls_controller_get_docx_path(monkeypatch):
    root = tk.Tk()
    opened = []
    monkeypatch.setattr("app.ui.history_view.os.startfile", lambda path: opened.append(path))
    controller = FakeController([_meeting(1, "Rapat A", "completed")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_download()

    assert opened == ["C:/recordings/1/mom.docx"]
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/ui/test_history_view.py -v`
Expected: FAIL — `app.ui.history_view` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `app/ui/history_view.py`:

```python
import logging
import os
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    "scheduled": "Terjadwal",
    "recording": "Merekam",
    "recorded": "Siap ditranskrip",
    "transcribing": "Sedang transkrip...",
    "transcribed": "Siap diringkas",
    "summarizing": "Sedang membuat ringkasan...",
    "completed": "Selesai",
    "failed": "Gagal",
}

_REFRESH_INTERVAL_MS = 2000


class HistoryView(tk.Frame):
    def __init__(self, parent: tk.Widget, controller):
        super().__init__(parent)
        self._controller = controller
        self._meetings_by_iid: dict[str, object] = {}

        self._tree = ttk.Treeview(self, columns=("title", "date", "status"), show="headings", height=10)
        self._tree.heading("title", text="Judul")
        self._tree.heading("date", text="Tanggal")
        self._tree.heading("status", text="Status")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        action_frame = tk.Frame(self)
        action_frame.pack(fill="x", pady=4)
        self._status_label = tk.Label(action_frame, text="")
        self._status_label.pack(anchor="w")

        self._transcribe_button = tk.Button(action_frame, text="Transkrip", command=self._handle_transcribe)
        self._summarize_button = tk.Button(action_frame, text="Ringkasan", command=self._handle_summarize)
        self._retry_button = tk.Button(action_frame, text="Coba Lagi", command=self._handle_retry)
        self._download_button = tk.Button(action_frame, text="Unduh Docx", command=self._handle_download)
        self._view_transcript_button = tk.Button(action_frame, text="Lihat Transkrip", command=self._handle_view_transcript)

        self._transcript_view = scrolledtext.ScrolledText(self, height=10, width=60)

        self.refresh()
        self.after(_REFRESH_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        self.refresh()
        self.after(_REFRESH_INTERVAL_MS, self._poll)

    def refresh(self) -> None:
        meetings = self._controller.list_meetings()
        previously_selected = self._tree.selection()
        self._tree.delete(*self._tree.get_children())
        self._meetings_by_iid.clear()
        for meeting in meetings:
            date_str = meeting.start_time.strftime("%Y-%m-%d %H:%M") if meeting.start_time else "-"
            iid = str(meeting.id)
            self._tree.insert("", "end", iid=iid, values=(
                meeting.title, date_str, _STATUS_LABELS.get(meeting.status, meeting.status),
            ))
            self._meetings_by_iid[iid] = meeting
        if previously_selected and previously_selected[0] in self._meetings_by_iid:
            self._tree.selection_set(previously_selected[0])
        self._update_action_panel()

    def _selected_meeting(self):
        selection = self._tree.selection()
        if not selection:
            return None
        return self._meetings_by_iid.get(selection[0])

    def _on_select(self, event=None) -> None:
        self._update_action_panel()

    def _update_action_panel(self) -> None:
        for button in (
            self._transcribe_button, self._summarize_button, self._retry_button,
            self._download_button, self._view_transcript_button,
        ):
            button.pack_forget()
        self._transcript_view.pack_forget()

        meeting = self._selected_meeting()
        if meeting is None:
            self._status_label.config(text="")
            return

        status = meeting.status
        label = _STATUS_LABELS.get(status, status)
        if status == "failed" and meeting.error_message:
            label = f"{label} -- {meeting.error_message}"
        self._status_label.config(text=label)

        if status == "recorded":
            self._transcribe_button.pack(side="left")
        elif status == "transcribed":
            self._summarize_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "completed":
            self._download_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "failed":
            self._retry_button.pack(side="left")

    def _run_in_background(self, fn, meeting_id: int) -> None:
        def _worker():
            try:
                fn(meeting_id)
            except Exception as exc:
                logger.warning("history action failed for meeting %s: %s", meeting_id, exc)
            finally:
                self.after(0, self.refresh)

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_transcribe(self) -> None:
        meeting = self._selected_meeting()
        if meeting is not None:
            self._run_in_background(self._controller.run_transcribe, meeting.id)

    def _handle_summarize(self) -> None:
        meeting = self._selected_meeting()
        if meeting is not None:
            self._run_in_background(self._controller.run_summarize, meeting.id)

    def _handle_retry(self) -> None:
        meeting = self._selected_meeting()
        if meeting is not None:
            self._run_in_background(self._controller.retry, meeting.id)

    def _handle_download(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None:
            return
        docx_path = self._controller.get_docx_path(meeting.id)
        if docx_path:
            os.startfile(docx_path)

    def _handle_view_transcript(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None:
            return
        rows = self._controller.get_transcript(meeting.id)
        self._transcript_view.pack(fill="both", expand=True)
        self._transcript_view.delete("1.0", "end")
        for label, text in rows:
            self._transcript_view.insert("end", f"{label}: {text}\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/ui/test_history_view.py -v`
Expected: PASS (or all SKIPPED if no display is available in the test environment — acceptable, matches the existing `test_window.py` convention)

- [ ] **Step 5: Commit**

```bash
git add app/ui/history_view.py tests/ui/test_history_view.py
git commit -m "feat(fase3): add HistoryView -- Treeview meeting list with per-status action buttons"
```

---

## Task 7: `MainWindow` — two tabs (Meeting Baru / Riwayat)

**Files:**
- Modify: `app/ui/window.py` (full rewrite)
- Modify: `tests/ui/test_window.py` (remove tests for widgets that no longer exist: progress bar, open-docx button; add a tab-switch test)

**Interfaces:**
- Consumes: `HistoryView` (Task 6)
- Produces: `MainWindow(root, controller)` — same public attributes as before for the recording tab (`title_var`, `_title_entry`, `_start_button`, `_stop_button`, `status_var`, `status_label`, `transcript_view`, `push_live_event()`) so Task 6/existing live-preview wiring in `main.py` (`window.push_live_event`) keeps working unchanged. **Removed**: `progress_step_var`, `_progress_bar`, `_open_docx_button`, `_handle_open_docx` (the flow they served no longer exists on this tab). **Added**: `_history_view` (the `HistoryView` instance), `_recording_frame`, nav buttons.

- [ ] **Step 1: Update the failing tests**

In `tests/ui/test_window.py`:
1. Delete `test_open_docx_button_enabled_only_when_done_with_result` and `test_open_docx_button_calls_os_startfile` (the button they test is removed).
2. Delete `test_progress_step_label_reflects_controller_processing_step` — wait, this test does not exist in the base file (it was added earlier this session in a prior task); delete it along with the other progress-bar test if present.
3. In `test_status_label_color_reflects_state`, remove the `"processing"` and `"done"` cases (those states are no longer reachable from `RecorderController` per Task 5) — keep only:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_status_label_color_reflects_state():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    controller.state = "recording"
    window.refresh_status()
    assert window.status_label.cget("fg") == "red"

    controller.state = "error"
    window.refresh_status()
    assert window.status_label.cget("fg") == "red"

    root.destroy()
```

4. In `FakeController` (top of the file), remove `self.last_docx_path` (no longer read by `MainWindow`).
5. Add a new test for tab switching, appended near the end of the file:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_nav_buttons_switch_between_recording_and_history_frames():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    # Recording frame is the default view.
    assert window._recording_frame.winfo_ismapped() or str(window._recording_frame.winfo_manager()) == "grid"

    window._show_history()
    assert window._history_view.winfo_viewable()

    window._show_recording()
    assert window._recording_frame.winfo_viewable()

    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/ui/test_window.py -v`
Expected: FAIL — `MainWindow` doesn't have `_show_history`/`_show_recording`/`_history_view` yet; `_open_docx_button`/progress-bar attributes still referenced by old tests until Step 1's edits are fully applied (the removal happens in Step 1, so after that this failure is purely about the missing tab-switch API).

- [ ] **Step 3: Implement**

Replace the entire contents of `app/ui/window.py`:

```python
# app/ui/window.py
import sys
import tkinter as tk
from tkinter import scrolledtext
import threading
import queue

from app.ui.controller import RecorderController
from app.ui.history_view import HistoryView

_STATUS_LABELS = {
    "idle": "Siap",
    "recording": "Sedang merekam...",
    "error": "Gagal, lihat log",
}

_STATUS_COLORS = {
    "idle": "black",
    "recording": "red",
    "error": "red",
}


class MainWindow:
    def __init__(self, root: tk.Tk, controller: RecorderController):
        self._root = root
        self._controller = controller
        self._root.title("Meeting Recorder")

        nav = tk.Frame(root)
        nav.pack(fill="x")
        tk.Button(nav, text="Meeting Baru", command=self._show_recording).pack(side="left")
        tk.Button(nav, text="Riwayat", command=self._show_history).pack(side="left")

        container = tk.Frame(root)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._recording_frame = tk.Frame(container)
        self._recording_frame.grid(row=0, column=0, sticky="nsew")
        self._build_recording_frame(self._recording_frame)

        self._history_view = HistoryView(container, controller)
        self._history_view.grid(row=0, column=0, sticky="nsew")

        self._show_recording()

    def _show_recording(self) -> None:
        self._recording_frame.tkraise()

    def _show_history(self) -> None:
        self._history_view.tkraise()
        self._history_view.refresh()

    def _build_recording_frame(self, parent: tk.Widget) -> None:
        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value=_STATUS_LABELS["idle"])

        tk.Label(parent, text="Judul Meeting:").pack(anchor="w")
        self._title_entry = tk.Entry(parent, textvariable=self.title_var, width=40)
        self._title_entry.pack(fill="x")

        button_frame = tk.Frame(parent)
        button_frame.pack(fill="x", pady=4)
        self._start_button = tk.Button(button_frame, text="Mulai Rekam", command=self._handle_start)
        self._start_button.pack(side="left")
        self._stop_button = tk.Button(button_frame, text="Stop Rekam", command=self._handle_stop)
        self._stop_button.pack(side="left")

        self.status_label = tk.Label(parent, textvariable=self.status_var)
        self.status_label.pack(anchor="w")

        self.transcript_view = scrolledtext.ScrolledText(parent, height=15, width=60)
        self.transcript_view.pack(fill="both", expand=True)

        self._live_events: "queue.Queue" = queue.Queue()
        self._root.after(200, self._drain_live_events)

    def _handle_start(self) -> None:
        self.on_start_clicked(self.title_var.get())

    def _handle_stop(self) -> None:
        self.on_stop_clicked()

    def on_start_clicked(self, title: str) -> None:
        if self._controller.state not in ("idle", "error"):
            return

        self._start_button.config(state="disabled")

        def _start_in_background():
            try:
                self._controller.start_meeting(title)
            except Exception as exc:
                print(f"Error starting meeting: {exc}", file=sys.stderr)
            finally:
                self._root.after(0, self.refresh_status)

        threading.Thread(target=_start_in_background, daemon=True).start()

    def on_stop_clicked(self) -> None:
        if self._controller.state != "recording":
            return

        self._stop_button.config(state="disabled")

        def _stop_in_background():
            try:
                self._controller.stop_meeting()
            except Exception as exc:
                print(f"Error stopping meeting: {exc}", file=sys.stderr)
            finally:
                self._root.after(0, self.refresh_status)
                self._root.after(0, self._history_view.refresh)

        threading.Thread(target=_stop_in_background, daemon=True).start()

    def refresh_status(self) -> None:
        state = self._controller.state
        status = _STATUS_LABELS.get(state, state)
        if state == "error" and self._controller.error_message:
            status = f"{status}: {self._controller.error_message}"
        self.status_var.set(status)
        self.status_label.config(fg=_STATUS_COLORS.get(state, "black"))
        is_idle = state in ("idle", "error")
        self._start_button.config(state="normal" if is_idle else "disabled")
        self._stop_button.config(state="normal" if state == "recording" else "disabled")
        self._title_entry.config(state="normal" if is_idle else "disabled")

    def push_live_event(self, event: dict) -> None:
        """Thread-safe: called from LiveSession's background threads."""
        self._live_events.put(event)

    def _is_scrolled_to_bottom(self) -> bool:
        _, bottom_fraction = self.transcript_view.yview()
        return bottom_fraction >= 0.999

    def _drain_live_events(self) -> None:
        try:
            while True:
                event = self._live_events.get_nowait()
                if event["type"] == "text":
                    segment = event["segment"]
                    if segment is not None:
                        follow = self._is_scrolled_to_bottom()
                        self.transcript_view.insert("end", f"{segment.text}\n")
                        if follow:
                            self.transcript_view.see("end")
                elif event["type"] == "relabel":
                    follow = self._is_scrolled_to_bottom()
                    scroll_fraction = self.transcript_view.yview()[0]
                    self.transcript_view.delete("1.0", "end")
                    for seg in event["segments"]:
                        self.transcript_view.insert("end", f"{seg.speaker_label}: {seg.text}\n")
                    if follow:
                        self.transcript_view.see("end")
                    else:
                        self.transcript_view.yview_moveto(scroll_fraction)
        except queue.Empty:
            pass
        finally:
            self._root.after(200, self._drain_live_events)
```

Note: `stop_meeting()`'s completion now also refreshes `_history_view` (Step 3's `_stop_in_background`) so the just-stopped meeting appears immediately in Riwayat without waiting for the next 2-second poll.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/ui/test_window.py -v`
Expected: PASS (or SKIPPED if no display)

- [ ] **Step 5: Commit**

```bash
git add app/ui/window.py tests/ui/test_window.py
git commit -m "feat(fase3): MainWindow -- split into Meeting Baru / Riwayat tabs, drop the old auto-processing progress UI"
```

---

## Task 8: `main.py` rewiring

**Files:**
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `transcribe_and_diarize` (Task 2), `summarize_and_export` (Task 3), `recover_abandoned_meetings` (Task 4), `RecorderController(transcribe_fn=..., summarize_fn=...)` (Task 5)
- No new public interfaces — this task only rewires existing pieces.

- [ ] **Step 1: Implement**

In `app/main.py`, change the imports (remove `finalize_meeting`, add the new pipeline functions and recovery):

```python
from app.pipeline.recovery import recover_abandoned_meetings
from app.pipeline.summarize import summarize_and_export
from app.pipeline.transcribe import transcribe_and_diarize
```

(remove the line `from app.pipeline.finalize import finalize_meeting`)

Replace the `finalize_fn` closure and `load_models` block in `main()` with:

```python
    # Heavy models are loaded on the first Transkrip/Ringkasan click, not at
    # startup: the window must appear at once, and a meeting sitting in
    # Riwayat waiting to be processed shouldn't cost anything until clicked.
    models = None

    def load_models():
        nonlocal models
        if models is None:
            models = build_models(backend_name, settings)
        return models

    async def transcribe_fn(meeting_id, mic_wav, speaker_wav):
        transcriber, diarizer, _summarizer = load_models()
        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, diarizer)

    async def summarize_fn(meeting_id, meeting_title, meeting_date):
        _transcriber, _diarizer, summarizer = load_models()
        docx_filename = build_docx_filename(meeting_date, meeting_title)
        docx_path = settings.recordings_dir / str(meeting_id) / docx_filename
        await summarize_and_export(session_factory, meeting_id, meeting_title, meeting_date, docx_path, summarizer)
```

Change the `RecorderController(...)` construction:

```python
    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=_real_recorder,
        transcribe_fn=transcribe_fn,
        summarize_fn=summarize_fn,
        recordings_dir=settings.recordings_dir,
        live_session_factory=live_session_factory,
    )
```

Right after `session_factory = make_session_factory(engine)` near the top of `main()`, add the startup recovery call (silent, no dialog — abandoned meetings just reappear in Riwayat with the right status):

```python
    recovered = asyncio.run(recover_abandoned_meetings(session_factory))
    if recovered:
        logger.info("recovered %d meeting(s) orphaned by a previous crash: %s", len(recovered), recovered)
```

- [ ] **Step 2: Run the full test suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, all tests (no more `ImportError` for `app.pipeline.finalize`)

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat(fase3): wire transcribe/summarize actions and silent startup recovery into main.py"
```

---

## Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, 0 failures

- [ ] **Step 2: Grep for any remaining references to removed names**

Run: `grep -rn "finalize_fn\|last_docx_path\|processing_step\|finalize_meeting" app/ tests/`
Expected: no output (everything migrated in Tasks 2-8)

- [ ] **Step 3: Manually smoke-test against the real Postgres DB**

This cannot be automated — ask the user to run `python -m app.main` and verify:
1. Window opens showing "Meeting Baru" tab by default.
2. Start → speak → Stop: app returns to idle immediately (no long wait), meeting appears in "Riwayat" tab with status "Siap ditranskrip".
3. Click the meeting row, click "Transkrip": status changes to "Sedang transkrip...", then "Siap diringkas" once done.
4. Click "Ringkasan": status changes to "Sedang membuat ringkasan...", then "Selesai".
5. "Unduh Docx" opens the generated file.
6. "Lihat Transkrip" shows the saved transcript text.
7. Start a NEW meeting while an older one's Transkrip/Ringkasan is still running — confirm both proceed without the app freezing or the new recording being blocked.

- [ ] **Step 4: Report results to the user**

No commit for this task — it is verification only.
