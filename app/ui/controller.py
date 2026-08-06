import asyncio
import logging
import shutil
import subprocess
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from app.storage import repository as repo
from app.storage.models import Meeting
from app.sync import minio_client

logger = logging.getLogger(__name__)


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)


def _extract_audio_to_wav(source: Path, dest: Path) -> None:
    """Uses ffmpeg to pull the audio track out of any file (audio or video)
    into a plain 16kHz mono WAV -- the one format every backend in app/asr/
    and the diarizer (stdlib `wave`, no arbitrary-container support) already
    knows how to read. ffmpeg is an optional runtime dep (see
    check_ffmpeg_available in main.py) so it's checked explicitly here rather
    than surfacing as a cryptic FileNotFoundError from subprocess."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg tidak ditemukan. Pasang dengan: winget install ffmpeg, "
            "lalu buka ulang Rekamind."
        )
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg gagal membaca {source.name}: {result.stderr[-500:]}")


def _write_silence_wav(path: Path, seconds: float = 1.0) -> None:
    """Placeholder mic.wav for an imported meeting: transcribe_and_diarize
    always transcribes mic_wav separately from speaker_wav (spec: "Anda" vs
    diarized speakers), but an imported recording is a single mixed track
    with no separate mic channel -- it all goes to speaker.wav instead, where
    diarization actually runs. A near-silent file keeps every downstream
    reader (wave.open, the transcriber) happy without special-casing "no mic
    track" through the rest of the pipeline."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * int(seconds * 16000))


class RecorderController:
    def __init__(
        self,
        session_factory,
        recorder_factory: Callable,
        transcribe_fn: Callable[..., Awaitable],
        summarize_fn: Callable[..., Awaitable],
        recordings_dir: Path,
        live_session_factory: Callable[[Path, Path, Path], object] | None = None,
        device_id: str | None = None,
        device_label: str | None = None,
        settings=None,
    ):
        self._session_factory = session_factory
        self._recorder_factory = recorder_factory
        self._transcribe_fn = transcribe_fn
        self._summarize_fn = summarize_fn
        self._recordings_dir = recordings_dir
        self._live_session_factory = live_session_factory
        self._device_id = device_id
        self._device_label = device_label
        self._settings = settings
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
                    device_id=self._device_id, device_label=self._device_label,
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

    def import_meeting(self, title: str, source_path: str) -> int:
        """Blocking -- call from a background thread. Creates a meeting
        straight from an already-recorded audio/video file, skipping Mulai
        Rekam/Stop Rekam entirely: it lands in Riwayat with status "recorded",
        ready for Transkrip/Ringkasan like any meeting captured live."""
        source = Path(source_path)
        if not source.exists():
            raise ValueError(f"File tidak ditemukan: {source_path}")

        session_dirname = uuid.uuid4().hex
        meeting_dir = self._recordings_dir / session_dirname
        meeting_dir.mkdir(parents=True, exist_ok=True)
        mic_path = meeting_dir / "mic.wav"
        speaker_path = meeting_dir / "speaker.wav"

        try:
            _extract_audio_to_wav(source, speaker_path)
            _write_silence_wav(mic_path)

            async def _create():
                async with self._session_factory() as session:
                    meeting = await repo.create_meeting(
                        session, title, datetime.now(timezone.utc), recording_dir=str(meeting_dir),
                        device_id=self._device_id, device_label=self._device_label,
                    )
                    await repo.start_recording(session, meeting.id)
                    await repo.stop_recording(session, meeting.id)
                    await repo.save_recording_file(
                        session, meeting.id, str(mic_path), "mic", _wav_duration_ms(mic_path)
                    )
                    await repo.save_recording_file(
                        session, meeting.id, str(speaker_path), "speaker", _wav_duration_ms(speaker_path)
                    )
                    await session.commit()
                    return meeting.id

            return asyncio.run(_create())
        except Exception:
            shutil.rmtree(meeting_dir, ignore_errors=True)
            raise

    def _ensure_audio_files(self, meeting: Meeting) -> None:
        """A meeting pulled from another device (see app/sync/minio_client.py)
        has a DB row here but its mic.wav/speaker.wav only ever lived on the
        recording device's own disk -- fetch them from MinIO on demand, same
        lazy-download pattern as ensure_docx_available() uses for mom.docx,
        so Transkrip works on a meeting this device didn't record."""
        if meeting.device_id == self._device_id or meeting.recording_dir is None:
            return
        recording_dir = Path(meeting.recording_dir)
        mic_path = recording_dir / "mic.wav"
        speaker_path = recording_dir / "speaker.wav"
        if mic_path.exists() and speaker_path.exists():
            return
        if self._settings is None or not self._settings.minio_is_configured:
            raise RuntimeError(
                "Rekaman ini ada di device lain dan sync (MinIO) belum diatur "
                "di device ini, jadi filenya tidak bisa diambil."
            )
        meeting_dir_name = recording_dir.name
        for path in (mic_path, speaker_path):
            if not path.exists():
                minio_client.download_file(
                    self._settings, meeting.device_id, meeting_dir_name, path.name, path,
                )

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
            # Outside the session block: a MinIO download of a large WAV
            # shouldn't hold a DB session/connection open for its duration.
            self._ensure_audio_files(meeting)
            await self._transcribe_fn(meeting_id=meeting_id, mic_wav=mic_wav, speaker_wav=speaker_wav)

        asyncio.run(_run())

    def run_summarize(self, meeting_id: int) -> None:
        """Blocking -- call from a background thread."""
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
                        "tidak bisa diringkas"
                    )
                title = meeting.title
                date = meeting.start_time or meeting.created_at
                recording_dir = meeting.recording_dir
            await self._summarize_fn(
                meeting_id=meeting_id, meeting_title=title, meeting_date=date,
                recording_dir=recording_dir,
            )

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

    @property
    def minio_configured(self) -> bool:
        return self._settings is not None and self._settings.minio_is_configured

    def sync_now(self) -> dict:
        """Blocking -- call from a background thread."""
        push_result = minio_client.push(self._session_factory, self._settings)
        pull_result = minio_client.pull(self._session_factory, self._settings)
        return {**push_result, **pull_result}

    @property
    def local_device_id(self) -> str | None:
        return self._device_id

    def ensure_docx_available(self, meeting_id: int) -> str | None:
        """Blocking -- call from a background thread. Downloads the docx from
        MinIO on demand if it isn't on disk locally yet -- not just for a
        meeting pulled from another device, but also for a meeting THIS
        device recorded but had summarized elsewhere (see
        _ensure_audio_files/run_transcribe): that docx only ever gets pushed
        to MinIO by the device that made it, never copied back here on its
        own, so "it's my own meeting" is no longer a guarantee the file is
        already local."""
        async def _get():
            async with self._session_factory() as session:
                meeting = await session.get(Meeting, meeting_id)
                summary = await repo.get_summary(session, meeting_id)
                return meeting, summary

        meeting, summary = asyncio.run(_get())
        if summary is None or summary.docx_path is None:
            return None
        docx_path = Path(summary.docx_path)
        if docx_path.exists():
            return str(docx_path)
        # meeting can be None (row deleted between the two queries above),
        # have no recording_dir (legacy row predating that column), or have
        # no device_id (ditto) -- either way there's no remote object name to
        # build, so nothing to fetch.
        if meeting is None or meeting.recording_dir is None or meeting.device_id is None:
            return None
        if self._settings is None or not self._settings.minio_is_configured:
            raise RuntimeError(
                "Docx meeting ini belum ada di device ini dan sync (MinIO) "
                "belum diatur, jadi tidak bisa diambil."
            )
        meeting_dir_name = Path(meeting.recording_dir).name
        minio_client.download_file(
            self._settings, meeting.device_id, meeting_dir_name, "mom.docx", docx_path,
        )
        return str(docx_path)

    def get_docx_path(self, meeting_id: int) -> str | None:
        async def _get():
            async with self._session_factory() as session:
                summary = await repo.get_summary(session, meeting_id)
                return summary.docx_path if summary else None

        return asyncio.run(_get())
