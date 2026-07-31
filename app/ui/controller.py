import asyncio
import logging
import shutil
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
                if meeting.recording_dir is None:
                    # Legacy rows predate Meeting.recording_dir. Without this the
                    # bare TypeError from Path(None) surfaces as a silent no-op.
                    raise ValueError(
                        "Meeting ini tidak punya lokasi rekaman yang tersimpan, "
                        "tidak bisa ditranskrip"
                    )
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

    def delete_meeting(self, meeting_id: int) -> None:
        """Blocking -- call from a background thread. Irreversible: drops the
        DB rows and the meeting's whole recordings/<id>/ directory (WAVs,
        live scratch files, exported docx)."""
        if self._meeting_id == meeting_id and self.state == "recording":
            raise ValueError("Tidak bisa menghapus meeting yang sedang direkam")

        async def _delete():
            async with self._session_factory() as session:
                recording_dir = await repo.delete_meeting(session, meeting_id)
                await session.commit()
                return recording_dir

        recording_dir = asyncio.run(_delete())
        if recording_dir:
            shutil.rmtree(recording_dir, ignore_errors=True)

    def get_docx_path(self, meeting_id: int) -> str | None:
        async def _get():
            async with self._session_factory() as session:
                summary = await repo.get_summary(session, meeting_id)
                return summary.docx_path if summary else None

        return asyncio.run(_get())
