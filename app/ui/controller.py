import asyncio
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from app.storage import repository as repo


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)


class RecorderController:
    def __init__(
        self,
        session_factory,
        recorder_factory: Callable,
        finalize_fn: Callable[..., Awaitable],
        recordings_dir: Path,
        live_session_factory: Callable[[Path, Path, Path], object] | None = None,
    ):
        self._session_factory = session_factory
        self._recorder_factory = recorder_factory
        self._finalize_fn = finalize_fn
        self._recordings_dir = recordings_dir
        self._live_session_factory = live_session_factory
        self.state = "idle"
        self.error_message: str | None = None
        self._meeting_id: int | None = None
        self._meeting_title: str | None = None
        self._recorder = None
        self._live_session = None
        self.last_docx_path: str | None = None
        self.processing_step: str = ""

    def _set_processing_step(self, step: str) -> None:
        self.processing_step = step

    def _stop_live_session(self) -> None:
        """Stopping live preview must never mask the real error or block the
        recorder from being stopped -- it is best-effort, spec §5."""
        if self._live_session is None:
            return
        try:
            self._live_session.stop()
        except Exception as exc:
            print(f"WARNING: live session failed to stop cleanly: {exc}")
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
                print(f"WARNING: live preview unavailable this meeting: {exc}")
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
                meeting = await repo.create_meeting(session, title, datetime.now(timezone.utc))
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
        if self._recorder is None:
            raise RuntimeError("cannot stop: no meeting is currently being recorded")

        self._stop_live_session()

        mic_path, speaker_path = self._recorder.stop()
        self.state = "processing"
        self.processing_step = "Menyimpan rekaman..."

        async def _finalize():
            # Commit the recording metadata first, in its own transaction: if
            # finalize_fn later fails, end_time and the WAV file references must
            # still be on disk-of-record instead of being rolled back with it.
            async with self._session_factory() as session:
                await repo.stop_recording(session, self._meeting_id)
                await repo.save_recording_file(
                    session, self._meeting_id, str(mic_path), "mic", _wav_duration_ms(mic_path)
                )
                await repo.save_recording_file(
                    session, self._meeting_id, str(speaker_path), "speaker", _wav_duration_ms(speaker_path)
                )
                await session.commit()

            async with self._session_factory() as session:
                summary = await self._finalize_fn(
                    session=session,
                    meeting_id=self._meeting_id,
                    meeting_title=self._meeting_title,
                    meeting_date=datetime.now(),
                    mic_wav=mic_path,
                    speaker_wav=speaker_path,
                    on_progress=self._set_processing_step,
                )
                await session.commit()
                return summary.docx_path

        try:
            self.last_docx_path = asyncio.run(_finalize())
            self.state = "done"
            self._recorder = None
        except Exception as exc:
            self.error_message = f"Gagal memproses hasil rekaman: {exc}"
            self.state = "error"
            raise
        finally:
            self.processing_step = ""
