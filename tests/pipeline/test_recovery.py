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
