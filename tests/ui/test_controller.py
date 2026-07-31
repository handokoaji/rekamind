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


def test_run_transcribe_raises_clear_message_when_recording_dir_is_null(tmp_path):
    """Legacy rows can have recording_dir NULL. Path(None) raised a bare
    TypeError from inside pathlib, which the history view only logged -- the
    button looked like it did nothing at all."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    calls = []

    async def spy_transcribe_fn(meeting_id, mic_wav, speaker_wav):
        calls.append(meeting_id)

    controller = _make_controller(tmp_path, session_factory, transcribe_fn=spy_transcribe_fn)

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Lama", None, recording_dir=None)
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())

    try:
        controller.run_transcribe(meeting_id)
        assert False, "expected ValueError, not a TypeError from pathlib"
    except ValueError as exc:
        assert "tidak punya lokasi rekaman" in str(exc)

    assert calls == [], "transcription must not be attempted without a recording dir"


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
