import asyncio
import pytest
from datetime import datetime, timezone

from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo


def test_full_meeting_lifecycle():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Sprint Review", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.start_recording(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            speaker = await repo.get_or_create_speaker(session, meeting_id, "Speaker 1")
            await session.commit()
            speaker_id = speaker.id

        async with session_factory() as session:
            await repo.save_recording_file(session, meeting_id, "./recordings/1/mic.wav", "mic", 5000)
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 900, "text": "Selamat pagi"},
                {"meeting_id": meeting_id, "speaker_id": speaker_id, "source": "speaker",
                 "start_ms": 900, "end_ms": 2000, "text": "Pagi, mulai ya"},
            ])
            await repo.stop_recording(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            summary = await repo.save_summary(
                session, meeting_id, mom_json="{\"catatan\": \"ok\"}",
                docx_path="./recordings/1/mom.docx", groq_model="llama-3.3-70b-versatile",
                status="ready",
            )
            await repo.mark_meeting_status(session, meeting_id, "completed")
            await session.commit()
            summary_id = summary.id

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)

        return meeting_id, summary_id, meetings

    meeting_id, summary_id, meetings = asyncio.run(scenario())
    assert isinstance(meeting_id, int)
    assert isinstance(summary_id, int)
    assert len(meetings) == 1
    assert meetings[0].status == "completed"
    assert meetings[0].start_time is not None
    assert meetings[0].end_time is not None


def test_delete_meeting_removes_meeting_and_all_its_children():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Sprint Review", None, recording_dir="./recordings/abc",
            )
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            speaker = await repo.get_or_create_speaker(session, meeting_id, "Speaker 1")
            await repo.save_recording_file(session, meeting_id, "./recordings/abc/mic.wav", "mic", 5000)
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": speaker.id, "source": "speaker",
                 "start_ms": 0, "end_ms": 900, "text": "Halo"},
            ])
            await repo.save_summary(
                session, meeting_id, mom_json="{}", docx_path="./recordings/abc/mom.docx",
                groq_model="llama-3.3-70b-versatile", status="ready",
            )
            await session.commit()

        async with session_factory() as session:
            recording_dir = await repo.delete_meeting(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
            transcript = await repo.get_final_transcript(session, meeting_id)
            summary = await repo.get_summary(session, meeting_id)

        return recording_dir, meetings, transcript, summary

    recording_dir, meetings, transcript, summary = asyncio.run(scenario())
    assert recording_dir == "./recordings/abc"
    assert meetings == []
    assert transcript == []
    assert summary is None


def test_delete_meeting_raises_for_unknown_id():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            await repo.delete_meeting(session, 999)

    with pytest.raises(ValueError):
        asyncio.run(scenario())


def test_start_recording_missing_meeting():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            try:
                await repo.start_recording(session, 999)
                return False
            except ValueError as e:
                return "Meeting 999 not found" in str(e)

    result = asyncio.run(scenario())
    assert result is True


def test_stop_recording_missing_meeting():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            try:
                await repo.stop_recording(session, 999)
                return False
            except ValueError as e:
                return "Meeting 999 not found" in str(e)

    result = asyncio.run(scenario())
    assert result is True


def test_mark_meeting_status_missing_meeting():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            try:
                await repo.mark_meeting_status(session, 999, "failed")
                return False
            except ValueError as e:
                return "Meeting 999 not found" in str(e)

    result = asyncio.run(scenario())
    assert result is True


def test_save_transcript_segments_defaults_is_final_true():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Draft", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "final segment"},
            ])
            await session.commit()

        async with session_factory() as session:
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            result = await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )
            return result.scalars().all()

    segments = asyncio.run(scenario())
    assert len(segments) == 1
    assert segments[0].is_final is True


def test_save_summary_twice_updates_in_place_instead_of_raising_integrity_error():
    """Summary.meeting_id is unique: a second summarize (retry after a Groq
    failure, or a double-click) used to raise IntegrityError forever, leaving
    the meeting permanently stuck in "failed" with no in-app way out."""
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

            await repo.save_summary(
                session, meeting_id, mom_json='{"v": 1}', docx_path="C:/x/lama.docx",
                groq_model="llama-3.3-70b-versatile", status="ready",
            )
            await session.commit()

            summary = await repo.save_summary(
                session, meeting_id, mom_json='{"v": 2}', docx_path="C:/x/baru.docx",
                groq_model="llama-3.3-70b-versatile", status="ready",
            )
            await session.commit()

            from sqlalchemy import select
            from app.storage.models import Summary
            all_summaries = (await session.execute(
                select(Summary).where(Summary.meeting_id == meeting_id)
            )).scalars().all()
        return summary, all_summaries

    summary, all_summaries = asyncio.run(scenario())
    assert len(all_summaries) == 1, "must upsert, not insert a second row"
    assert summary.mom_json == '{"v": 2}'
    assert summary.docx_path == "C:/x/baru.docx"


def test_clear_all_segments_removes_finals_too():
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
                 "start_ms": 0, "end_ms": 400, "text": "draft", "is_final": False},
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 400, "end_ms": 800, "text": "final", "is_final": True},
            ])
            await session.commit()

            await repo.clear_all_segments(session, meeting_id)
            await session.commit()

            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            remaining = (await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )).scalars().all()
        return remaining

    assert asyncio.run(scenario()) == []


def test_save_transcript_segments_honors_is_final_false_and_clear_draft_segments_removes_only_drafts():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Draft", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "draft segment", "is_final": False},
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 500, "end_ms": 1000, "text": "final segment", "is_final": True},
            ])
            await session.commit()

        async with session_factory() as session:
            await repo.clear_draft_segments(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            result = await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )
            return result.scalars().all()

    segments = asyncio.run(scenario())
    assert len(segments) == 1
    assert segments[0].text == "final segment"
    assert segments[0].is_final is True


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
