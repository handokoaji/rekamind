import asyncio
import wave
from datetime import datetime
from pathlib import Path

from app.storage.db import make_engine, init_db, make_session_factory
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

    def start(self):
        self.started = True
        _write_silent_wav(self.mic_path)
        _write_silent_wav(self.speaker_path)

    def stop(self):
        return self.mic_path, self.speaker_path


def test_start_then_stop_meeting_transitions_state(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    finalize_calls = []

    async def fake_finalize_fn(**kwargs):
        finalize_calls.append(kwargs["meeting_id"])
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready",
                        docx_path="C:/recordings/1/mom.docx")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
    )

    assert controller.state == "idle"
    meeting_id = controller.start_meeting("Rapat Harian")
    assert controller.state == "recording"
    assert isinstance(meeting_id, int)

    controller.stop_meeting()
    assert controller.state == "done"
    assert finalize_calls == [meeting_id]
    assert controller.last_docx_path == "C:/recordings/1/mom.docx"


class BrokenRecorder:
    def __init__(self, mic_path, speaker_path):
        pass

    def start(self):
        raise OSError("no default input device")


def test_start_meeting_sets_error_state_when_device_missing(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    async def fake_finalize_fn(**kwargs):
        raise AssertionError("finalize should not be called when start fails")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: BrokenRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
    )

    try:
        controller.start_meeting("Rapat Gagal")
        assert False, "expected OSError to propagate"
    except OSError:
        pass

    assert controller.state == "error"
    assert "mic/speaker" in controller.error_message

    async def _list():
        async with session_factory() as session:
            from app.storage import repository as repo
            return await repo.list_meetings(session)

    assert asyncio.run(_list()) == []


def test_stop_meeting_sets_error_message_on_finalize_failure(tmp_path):
    """Bug fix #1: stop_meeting() must set error_message when exception occurs."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    async def failing_finalize_fn(**kwargs):
        raise ValueError("Database corruption detected")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=failing_finalize_fn,
        recordings_dir=tmp_path,
    )

    meeting_id = controller.start_meeting("Rapat Test")
    assert controller.state == "recording"

    try:
        controller.stop_meeting()
        assert False, "expected ValueError to propagate"
    except ValueError:
        pass

    assert controller.state == "error"
    assert controller.error_message is not None
    assert "Database corruption" in controller.error_message


def test_stop_meeting_raises_when_no_active_recording(tmp_path):
    """Bug fix #2: stop_meeting() must raise RuntimeError if no recorder is active."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
    )

    # stop_meeting() called without start_meeting()
    try:
        controller.stop_meeting()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "no meeting is currently being recorded" in str(e)

    # Also test calling stop_meeting() twice
    meeting_id = controller.start_meeting("Rapat Test")
    controller.stop_meeting()
    assert controller.state == "done"

    try:
        controller.stop_meeting()
        assert False, "expected RuntimeError on second stop"
    except RuntimeError as e:
        assert "no meeting is currently being recorded" in str(e)


class BrokenRecorderStartThenDB:
    """Recorder that starts successfully but simulates DB write failure."""
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


def test_db_failure_after_recorder_start_stops_recorder(tmp_path):
    """Bug fix #3: DB failure after successful recorder.start() must stop recorder to avoid leak."""
    from app.storage.models import Meeting

    async def fake_finalize_fn(**kwargs):
        raise AssertionError("finalize should not be called")

    # Use a real session factory for a real engine, but override commit to fail
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    real_session_factory = make_session_factory(engine)

    made_recorders = []

    def recorder_factory(mic, speaker):
        recorder = BrokenRecorderStartThenDB(mic, speaker)
        made_recorders.append(recorder)
        return recorder

    controller = RecorderController(
        session_factory=FailingSessionFactoryWrapper(real_session_factory),
        recorder_factory=recorder_factory,
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
    )

    try:
        controller.start_meeting("Rapat DB Fail")
        assert False, "expected RuntimeError from DB"
    except RuntimeError as e:
        assert "Simulated DB write failure" in str(e)

    # Verify state machine is set to error with message
    assert controller.state == "error"
    assert controller.error_message is not None
    assert "Gagal menyimpan data meeting" in controller.error_message
    # The actual point of this test: the started recorder was stopped, not leaked.
    assert len(made_recorders) == 1
    assert made_recorders[0].started is True
    assert made_recorders[0].stopped is True


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


def test_start_meeting_starts_live_session_when_factory_provided(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
    )

    meeting_id = controller.start_meeting("Rapat Live")
    assert len(created_sessions) == 1
    assert created_sessions[0].started is True
    # The live session only learns the meeting id once the row exists; without it
    # its draft writes stay disabled.
    assert created_sessions[0].meeting_id == meeting_id

    controller.stop_meeting()
    assert created_sessions[0].stopped is True


def _live_session_test_controller(tmp_path, live_session_cls, recorder_cls, session_factory):
    created = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = live_session_cls(mic_wav_path, speaker_wav_path, scratch_dir)
        created.append(live_session)
        return live_session

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: recorder_cls(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
    )
    return controller, created


def test_failing_live_session_stop_does_not_block_stop_meeting(tmp_path):
    """I3: a slow or broken live_session.stop() must never stop the recorder
    from being stopped or the meeting from being finalized."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    controller, created = _live_session_test_controller(
        tmp_path, BrokenStopLiveSession, FakeRecorder, session_factory
    )

    controller.start_meeting("Rapat Live Stop Gagal")
    controller.stop_meeting()

    assert created[0].stopped is True
    assert controller.state == "done"  # finalize still ran


def test_failing_live_session_stop_does_not_mask_recorder_start_error(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    controller, created = _live_session_test_controller(
        tmp_path, BrokenStopLiveSession, BrokenRecorder, session_factory
    )

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

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
    )

    controller.start_meeting("Rapat Tanpa Live")
    controller.stop_meeting()
    assert controller.state == "done"


def test_live_session_construction_failure_does_not_block_recording(tmp_path):
    """spec §5: live preview must never prevent the recording itself from starting."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    def broken_live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        raise RuntimeError("silero-vad model download failed")

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=broken_live_session_factory,
    )

    controller.start_meeting("Rapat Live Gagal")
    assert controller.state == "recording"  # recording still started despite live-session failure


def test_live_session_stopped_when_db_write_fails_after_it_started(tmp_path):
    """A live session that started successfully must not leak if the
    subsequent DB write for create_meeting fails. Reuses FailingSessionFactoryWrapper
    and BrokenRecorderStartThenDB, both already defined earlier in this file
    from Fase 1's Task 14."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    real_session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    async def fake_finalize_fn(**kwargs):
        raise AssertionError("finalize should not be called")

    controller = RecorderController(
        session_factory=FailingSessionFactoryWrapper(real_session_factory),
        recorder_factory=lambda mic, speaker: BrokenRecorderStartThenDB(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
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

    async def fake_finalize_fn(**kwargs):
        raise AssertionError("finalize should not be called")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: BrokenRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
    )

    try:
        controller.start_meeting("Rapat Recorder Fail")
        assert False, "expected OSError from recorder"
    except OSError:
        pass

    # Verify the live session was properly cleaned up
    assert len(created_sessions) == 1
    assert created_sessions[0].started is True
    assert created_sessions[0].stopped is True
    assert controller.state == "error"
