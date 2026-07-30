# Meeting Recorder — Fase 1 (Fondasi) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rekam meeting (mic + speaker loopback) ke WAV, simpan metadata ke Postgres, dan setelah rekaman berhenti proses batch (transcribe Bahasa Indonesia dengan large-v3, diarize speaker, generate MoM via Groq, export ke .docx) — dikontrol lewat window Tkinter + tray icon. Belum ada live preview real-time (itu Fase 2).

**Architecture:** Modul terpisah per tanggung jawab (audio capture, ASR backend per hardware, diarization, DB, summarization, UI) yang disatukan lewat satu fungsi orkestrasi `finalize_meeting`. Hardware (CUDA vs OpenVINO) dipilih otomatis lewat `asr.detect.detect_backend()` di belakang satu interface `TranscriberBackend`, jadi kode pipeline tidak peduli sedang jalan di desktop atau laptop.

**Tech Stack:** Python 3.14 (venv sudah ada), SQLAlchemy 2.0 async + asyncpg (Postgres) / aiosqlite (test), pyaudiowpatch (WASAPI capture Windows), faster-whisper (CUDA) / optimum-intel+OpenVINO (Intel NPU/GPU), pyannote.audio (diarization), groq (Python client resmi), python-docx, Tkinter + pystray, pytest + pytest-asyncio.

## Global Constraints

- OS target: Windows only (spec §2).
- `.env` tidak pernah masuk git — sudah di `.gitignore`; jangan pernah menuliskan isi token/kredensial ke file yang bisa ter-commit (spec §7, project memory).
- Backend ASR dipilih otomatis per hardware (CUDA di desktop GTX 1080 Ti, OpenVINO GPU/NPU di laptop Core Ultra 7 155H), lewat satu interface `TranscriberBackend` (spec §3, §4).
- Fase 1 memakai model `large-v3` untuk transkrip (belum ada model kecil live preview — itu Fase 2) (spec §11).
- Diarization hanya berjalan pada stream speaker/loopback; mic selalu berlabel "Anda" (spec §3).
- Audio WAV disimpan permanen di `./recordings/<meeting_id>/` (spec §5, §9).
- MoM di-generate via Groq model `llama-3.3-70b-versatile`, hasil disimpan ke DB dan di-export ke `.docx` rapi (spec §5, §6).
- DB: Postgres `meeting_recorder` di `10.55.11.209` (sudah dibuat); skema mengikuti spec §6 persis (meetings, speakers, transcript_segments, recordings, summaries).
- UI: Tkinter native saja, tanpa browser/web server, tanpa autentikasi, tanpa auto-start Windows (spec §8).
- Package manager: pip + `pyproject.toml` biasa.
- Bahasa UI: Bahasa Indonesia.

---

### Task 1: Project Scaffolding & Config

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`
- Create: `tests/__init__.py`
- Create: `pytest.ini`

**Interfaces:**
- Produces: `app.config.Settings` (pydantic BaseSettings) with fields `postgres_host: str`, `postgres_port: int`, `postgres_user: str`, `postgres_password: str`, `postgres_db: str`, `database_url: str`, `groq_api_key: str = ""`, `hf_token: str = ""`, `recordings_dir: Path = Path("./recordings")`, `asr_backend_override: str = ""`. Produces `app.config.get_settings() -> Settings`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "meeting-recorder"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic-settings>=2.4",
    "sqlalchemy>=2.0",
    "asyncpg>=0.29",
    "aiosqlite>=0.20",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
import os
from pathlib import Path

from app.config import get_settings


def test_settings_loads_from_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_HOST=localhost\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_USER=u\n"
        "POSTGRES_PASSWORD=p\n"
        "POSTGRES_DB=d\n"
        "DATABASE_URL=postgresql+asyncpg://u:p@localhost:5432/d\n"
    )
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.recordings_dir == Path("./recordings")
    assert settings.groq_api_key == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'` (or `ImportError`)

- [ ] **Step 4: Write minimal implementation**

```python
# app/__init__.py
```

```python
# app/config.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    database_url: str
    groq_api_key: str = ""
    hf_token: str = ""
    recordings_dir: Path = Path("./recordings")
    asr_backend_override: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# tests/__init__.py
```

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Install deps and commit**

```bash
./.venv/Scripts/python.exe -m pip install -e .
./.venv/Scripts/python.exe -m pip install pytest pytest-asyncio
git add pyproject.toml pytest.ini app/__init__.py app/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: add project scaffolding and env-based settings"
```

---

### Task 2: Database Models

**Files:**
- Create: `app/storage/__init__.py`
- Create: `app/storage/models.py`
- Test: `tests/storage/test_models.py`
- Create: `tests/storage/__init__.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.storage.models.Base` (DeclarativeBase), `Meeting`, `Speaker`, `TranscriptSegment`, `Recording`, `Summary` ORM classes exactly matching spec §6. `Meeting.status` is a plain `str` column holding one of `"scheduled"|"recording"|"processing"|"completed"|"failed"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/storage/test_models.py
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.storage.models import Base, Meeting, Speaker, TranscriptSegment, Recording, Summary


async def _make_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def test_meeting_with_related_rows_round_trips():
    async def scenario() -> int:
        session_factory = await _make_session_factory()
        async with session_factory() as session:
            meeting = Meeting(title="Standup", status="recording")
            session.add(meeting)
            await session.flush()

            speaker = Speaker(meeting_id=meeting.id, label="Speaker 1")
            session.add(speaker)
            await session.flush()

            session.add(TranscriptSegment(
                meeting_id=meeting.id, speaker_id=speaker.id,
                source="speaker", start_ms=0, end_ms=1000, text="halo semua",
            ))
            session.add(Recording(
                meeting_id=meeting.id, file_path="./recordings/1/speaker.wav",
                source="speaker", duration_ms=1000,
            ))
            session.add(Summary(
                meeting_id=meeting.id, mom_json="{}", groq_model="llama-3.3-70b-versatile",
                status="pending",
            ))
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(scenario())
    assert isinstance(meeting_id, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/storage/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.storage'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/storage/__init__.py
```

```python
# app/storage/models.py
from datetime import datetime, timezone

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    scheduled_time: Mapped[datetime | None] = mapped_column(default=None)
    start_time: Mapped[datetime | None] = mapped_column(default=None)
    end_time: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="scheduled")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    speakers: Mapped[list["Speaker"]] = relationship(back_populates="meeting")
    segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="meeting")
    recordings: Mapped[list["Recording"]] = relationship(back_populates="meeting")
    summary: Mapped["Summary | None"] = relationship(back_populates="meeting", uselist=False)


class Speaker(Base):
    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    label: Mapped[str]
    display_name: Mapped[str | None] = mapped_column(default=None)

    meeting: Mapped["Meeting"] = relationship(back_populates="speakers")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("speakers.id"), default=None)
    source: Mapped[str]
    start_ms: Mapped[int]
    end_ms: Mapped[int]
    text: Mapped[str]
    is_final: Mapped[bool] = mapped_column(default=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="segments")
    speaker: Mapped["Speaker | None"] = relationship()


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    file_path: Mapped[str]
    source: Mapped[str]
    duration_ms: Mapped[int]

    meeting: Mapped["Meeting"] = relationship(back_populates="recordings")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), unique=True)
    mom_json: Mapped[str]
    docx_path: Mapped[str | None] = mapped_column(default=None)
    groq_model: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    meeting: Mapped["Meeting"] = relationship(back_populates="summary")
```

```python
# tests/storage/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/storage/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/storage/__init__.py app/storage/models.py tests/storage/__init__.py tests/storage/test_models.py
git commit -m "feat: add SQLAlchemy models for meetings/speakers/segments/recordings/summaries"
```

---

### Task 3: DB Engine, Session Factory & Repository

**Files:**
- Create: `app/storage/db.py`
- Create: `app/storage/repository.py`
- Test: `tests/storage/test_repository.py`

**Interfaces:**
- Consumes: `app.storage.models.{Base,Meeting,Speaker,TranscriptSegment,Recording,Summary}` (Task 2).
- Produces:
  - `app.storage.db.make_engine(database_url: str) -> AsyncEngine`
  - `app.storage.db.init_db(engine: AsyncEngine) -> None` (creates all tables)
  - `app.storage.db.make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`
  - `app.storage.repository.create_meeting(session, title: str, scheduled_time: datetime | None) -> Meeting`
  - `app.storage.repository.start_recording(session, meeting_id: int) -> None`
  - `app.storage.repository.stop_recording(session, meeting_id: int) -> None`
  - `app.storage.repository.save_recording_file(session, meeting_id: int, file_path: str, source: str, duration_ms: int) -> Recording`
  - `app.storage.repository.get_or_create_speaker(session, meeting_id: int, label: str) -> Speaker`
  - `app.storage.repository.save_transcript_segments(session, segments: list[dict]) -> None` — each dict has keys `meeting_id, speaker_id, source, start_ms, end_ms, text`
  - `app.storage.repository.save_summary(session, meeting_id: int, mom_json: str, docx_path: str | None, groq_model: str, status: str) -> Summary`
  - `app.storage.repository.mark_meeting_status(session, meeting_id: int, status: str) -> None`
  - `app.storage.repository.list_meetings(session) -> list[Meeting]`

- [ ] **Step 1: Write the failing test**

```python
# tests/storage/test_repository.py
import asyncio
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/storage/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.storage.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/storage/db.py
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.storage.models import Base


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

```python
# app/storage/repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import Meeting, Recording, Speaker, Summary, TranscriptSegment


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_meeting(session: AsyncSession, title: str, scheduled_time: datetime | None) -> Meeting:
    meeting = Meeting(title=title, scheduled_time=scheduled_time, status="scheduled")
    session.add(meeting)
    await session.flush()
    return meeting


async def start_recording(session: AsyncSession, meeting_id: int) -> None:
    meeting = await session.get(Meeting, meeting_id)
    meeting.status = "recording"
    meeting.start_time = _utcnow()


async def stop_recording(session: AsyncSession, meeting_id: int) -> None:
    meeting = await session.get(Meeting, meeting_id)
    meeting.status = "processing"
    meeting.end_time = _utcnow()


async def save_recording_file(
    session: AsyncSession, meeting_id: int, file_path: str, source: str, duration_ms: int
) -> Recording:
    recording = Recording(meeting_id=meeting_id, file_path=file_path, source=source, duration_ms=duration_ms)
    session.add(recording)
    await session.flush()
    return recording


async def get_or_create_speaker(session: AsyncSession, meeting_id: int, label: str) -> Speaker:
    result = await session.execute(
        select(Speaker).where(Speaker.meeting_id == meeting_id, Speaker.label == label)
    )
    speaker = result.scalar_one_or_none()
    if speaker is not None:
        return speaker
    speaker = Speaker(meeting_id=meeting_id, label=label)
    session.add(speaker)
    await session.flush()
    return speaker


async def save_transcript_segments(session: AsyncSession, segments: list[dict]) -> None:
    for seg in segments:
        session.add(TranscriptSegment(
            meeting_id=seg["meeting_id"],
            speaker_id=seg.get("speaker_id"),
            source=seg["source"],
            start_ms=seg["start_ms"],
            end_ms=seg["end_ms"],
            text=seg["text"],
        ))
    await session.flush()


async def save_summary(
    session: AsyncSession, meeting_id: int, mom_json: str, docx_path: str | None,
    groq_model: str, status: str,
) -> Summary:
    summary = Summary(
        meeting_id=meeting_id, mom_json=mom_json, docx_path=docx_path,
        groq_model=groq_model, status=status,
    )
    session.add(summary)
    await session.flush()
    return summary


async def mark_meeting_status(session: AsyncSession, meeting_id: int, status: str) -> None:
    meeting = await session.get(Meeting, meeting_id)
    meeting.status = status


async def list_meetings(session: AsyncSession) -> list[Meeting]:
    result = await session.execute(select(Meeting).order_by(Meeting.created_at.desc()))
    return list(result.scalars().all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/storage/test_repository.py -v`
Expected: PASS

- [ ] **Step 5: Verify against the real Postgres server**

Run:
```bash
./.venv/Scripts/python.exe -c "
import asyncio
from app.config import get_settings
from app.storage.db import make_engine, init_db

async def main():
    settings = get_settings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    print('tables created on real Postgres')

asyncio.run(main())
"
```
Expected: prints `tables created on real Postgres` with no errors (uses the real `meeting_recorder` DB).

- [ ] **Step 6: Commit**

```bash
git add app/storage/db.py app/storage/repository.py tests/storage/test_repository.py
git commit -m "feat: add async DB engine, session factory, and meeting repository"
```

---

### Task 4: WAV File Writer

**Files:**
- Create: `app/audio/__init__.py`
- Create: `app/audio/wav_writer.py`
- Test: `tests/audio/test_wav_writer.py`
- Create: `tests/audio/__init__.py`

**Interfaces:**
- Produces: `app.audio.wav_writer.WavFileWriter(path: Path, samplerate: int, channels: int, sample_width: int = 2)` with methods `write_frames(frames: bytes) -> None`, `close() -> None`, and context-manager support (`__enter__`/`__exit__`).

- [ ] **Step 1: Write the failing test**

```python
# tests/audio/test_wav_writer.py
import wave

from app.audio.wav_writer import WavFileWriter


def test_writes_valid_wav_file(tmp_path):
    path = tmp_path / "out.wav"
    silence_frame = (0).to_bytes(2, "little", signed=True) * 160  # 10ms @16kHz mono

    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        writer.write_frames(silence_frame)
        writer.write_frames(silence_frame)

    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 320
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/audio/test_wav_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.audio'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/audio/__init__.py
```

```python
# app/audio/wav_writer.py
import wave
from pathlib import Path


class WavFileWriter:
    def __init__(self, path: Path, samplerate: int, channels: int, sample_width: int = 2):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wf = wave.open(str(path), "wb")
        self._wf.setnchannels(channels)
        self._wf.setsampwidth(sample_width)
        self._wf.setframerate(samplerate)

    def write_frames(self, frames: bytes) -> None:
        self._wf.writeframes(frames)

    def close(self) -> None:
        self._wf.close()

    def __enter__(self) -> "WavFileWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
```

```python
# tests/audio/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/audio/test_wav_writer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/audio/__init__.py app/audio/wav_writer.py tests/audio/__init__.py tests/audio/test_wav_writer.py
git commit -m "feat: add WAV file writer"
```

---

### Task 5: Audio Capture (Mic + Speaker Loopback)

**Files:**
- Create: `app/audio/capture.py`
- Test: `tests/audio/test_capture.py`

**Interfaces:**
- Consumes: `app.audio.wav_writer.WavFileWriter` (Task 4).
- Produces:
  - `app.audio.capture.AudioDeviceConfig(samplerate: int = 16000, channels: int = 1)` (dataclass)
  - `app.audio.capture.frame_callback(frames: bytes, writer: WavFileWriter) -> None` — pure glue function, unit-testable without real hardware.
  - `app.audio.capture.MicSpeakerRecorder(mic_path: Path, speaker_path: Path, config: AudioDeviceConfig | None = None)` with `start() -> None` and `stop() -> tuple[Path, Path]` (opens real WASAPI streams via `pyaudiowpatch`, marked `pytest.mark.hardware` — skipped by default, only the `frame_callback` glue is covered by the default fast suite).

- [ ] **Step 1: Write the failing test**

```python
# tests/audio/test_capture.py
from pathlib import Path

import pytest

from app.audio.capture import AudioDeviceConfig, frame_callback, MicSpeakerRecorder
from app.audio.wav_writer import WavFileWriter


def test_frame_callback_writes_frames_to_writer(tmp_path):
    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        frame_callback(frame, writer)
        frame_callback(frame, writer)

    import wave
    with wave.open(str(path), "rb") as wf:
        assert wf.getnframes() == 320


def test_config_defaults():
    config = AudioDeviceConfig()
    assert config.samplerate == 16000
    assert config.channels == 1


@pytest.mark.hardware
def test_real_capture_start_stop(tmp_path):
    recorder = MicSpeakerRecorder(tmp_path / "mic.wav", tmp_path / "speaker.wav")
    recorder.start()
    mic_path, speaker_path = recorder.stop()
    assert mic_path.exists()
    assert speaker_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/audio/test_capture.py -v -m "not hardware"`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.audio.capture'`

- [ ] **Step 3: Register the `hardware` marker and write minimal implementation**

```ini
# pytest.ini (append)
markers =
    hardware: requires real audio devices, skipped by default
addopts = -m "not hardware"
```

```python
# app/audio/capture.py
import threading
from dataclasses import dataclass
from pathlib import Path

from app.audio.wav_writer import WavFileWriter


@dataclass
class AudioDeviceConfig:
    samplerate: int = 16000
    channels: int = 1


def frame_callback(frames: bytes, writer: WavFileWriter) -> None:
    writer.write_frames(frames)


class MicSpeakerRecorder:
    """Captures mic input and WASAPI speaker loopback in parallel to two WAV files.

    Real device I/O uses pyaudiowpatch (Windows-only WASAPI loopback support).
    Import is deferred into start() so this module can be imported and the
    frame_callback logic tested on any platform without pyaudiowpatch installed.
    """

    def __init__(self, mic_path: Path, speaker_path: Path, config: AudioDeviceConfig | None = None):
        self._mic_path = mic_path
        self._speaker_path = speaker_path
        self._config = config or AudioDeviceConfig()
        self._pyaudio = None
        self._mic_stream = None
        self._speaker_stream = None
        self._mic_writer: WavFileWriter | None = None
        self._speaker_writer: WavFileWriter | None = None

    def start(self) -> None:
        import pyaudiowpatch as pyaudio

        self._pyaudio = pyaudio.PyAudio()
        self._mic_writer = WavFileWriter(self._mic_path, self._config.samplerate, self._config.channels)
        self._speaker_writer = WavFileWriter(self._speaker_path, self._config.samplerate, self._config.channels)

        default_speakers = self._pyaudio.get_default_wasapi_loopback()

        def mic_stream_callback(in_data, frame_count, time_info, status):
            frame_callback(in_data, self._mic_writer)
            return (None, pyaudio.paContinue)

        def speaker_stream_callback(in_data, frame_count, time_info, status):
            frame_callback(in_data, self._speaker_writer)
            return (None, pyaudio.paContinue)

        self._mic_stream = self._pyaudio.open(
            format=pyaudio.paInt16, channels=self._config.channels,
            rate=self._config.samplerate, input=True,
            stream_callback=mic_stream_callback,
        )
        self._speaker_stream = self._pyaudio.open(
            format=pyaudio.paInt16, channels=default_speakers["maxInputChannels"],
            rate=int(default_speakers["defaultSampleRate"]), input=True,
            input_device_index=default_speakers["index"],
            stream_callback=speaker_stream_callback,
        )
        self._mic_stream.start_stream()
        self._speaker_stream.start_stream()

    def stop(self) -> tuple[Path, Path]:
        for stream in (self._mic_stream, self._speaker_stream):
            if stream is not None:
                stream.stop_stream()
                stream.close()
        if self._pyaudio is not None:
            self._pyaudio.terminate()
        if self._mic_writer is not None:
            self._mic_writer.close()
        if self._speaker_writer is not None:
            self._speaker_writer.close()
        return self._mic_path, self._speaker_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/audio/test_capture.py -v`
Expected: PASS (2 passed, 1 deselected — the `hardware` test is skipped by default)

- [ ] **Step 5: Install pyaudiowpatch and commit**

```bash
./.venv/Scripts/python.exe -m pip install pyaudiowpatch
git add pyproject.toml pytest.ini app/audio/capture.py tests/audio/test_capture.py
git commit -m "feat: add mic+speaker WASAPI loopback capture"
```

(Add `"pyaudiowpatch"` to the `dependencies` list in `pyproject.toml` as part of this commit.)

---

### Task 6: ASR Hardware Backend Detection

**Files:**
- Create: `app/asr/__init__.py`
- Create: `app/asr/detect.py`
- Test: `tests/asr/test_detect.py`
- Create: `tests/asr/__init__.py`

**Interfaces:**
- Produces: `app.asr.detect.detect_backend(override: str = "") -> str`, returning `"cuda"`, `"openvino"`, or `"cpu"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/asr/test_detect.py
from app.asr import detect


def test_override_takes_priority():
    assert detect.detect_backend(override="cpu") == "cpu"
    assert detect.detect_backend(override="cuda") == "cuda"


def test_falls_back_to_cuda_when_available(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: True)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: False)
    assert detect.detect_backend() == "cuda"


def test_falls_back_to_openvino_when_cuda_missing(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: False)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: True)
    assert detect.detect_backend() == "openvino"


def test_falls_back_to_cpu_when_nothing_available(monkeypatch):
    monkeypatch.setattr(detect, "_cuda_available", lambda: False)
    monkeypatch.setattr(detect, "_openvino_gpu_or_npu_available", lambda: False)
    assert detect.detect_backend() == "cpu"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/asr/test_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.asr'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/asr/__init__.py
```

```python
# app/asr/detect.py
def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _openvino_gpu_or_npu_available() -> bool:
    try:
        import openvino as ov
        devices = ov.Core().available_devices
        return any(d.startswith("GPU") or d.startswith("NPU") for d in devices)
    except ImportError:
        return False


def detect_backend(override: str = "") -> str:
    if override:
        return override
    if _cuda_available():
        return "cuda"
    if _openvino_gpu_or_npu_available():
        return "openvino"
    return "cpu"
```

```python
# tests/asr/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/asr/test_detect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/asr/__init__.py app/asr/detect.py tests/asr/__init__.py tests/asr/test_detect.py
git commit -m "feat: add hardware backend auto-detection (CUDA/OpenVINO/CPU)"
```

---

### Task 7: ASR Backend Interface + CUDA Backend

**Files:**
- Create: `app/asr/base.py`
- Create: `app/asr/cuda_backend.py`
- Test: `tests/asr/test_base.py`
- Test: `tests/asr/test_cuda_backend.py`

**Interfaces:**
- Consumes: nothing new for `base.py`.
- Produces:
  - `app.asr.base.TranscriptSegmentResult` (dataclass: `start_ms: int, end_ms: int, text: str`)
  - `app.asr.base.TranscriberBackend` (Protocol with `transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]`)
  - `app.asr.cuda_backend.CudaWhisperBackend(model_size: str = "large-v3", device: str = "cuda", compute_type: str = "float16")` implementing `TranscriberBackend`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/asr/test_base.py
from pathlib import Path

from app.asr.base import TranscriberBackend, TranscriptSegmentResult


class FakeBackend:
    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        return [TranscriptSegmentResult(start_ms=0, end_ms=500, text="halo")]


def test_fake_backend_satisfies_protocol():
    backend: TranscriberBackend = FakeBackend()
    result = backend.transcribe(Path("dummy.wav"))
    assert result == [TranscriptSegmentResult(start_ms=0, end_ms=500, text="halo")]
```

```python
# tests/asr/test_cuda_backend.py
from unittest.mock import MagicMock

import pytest

from app.asr.cuda_backend import CudaWhisperBackend


def test_transcribe_maps_faster_whisper_segments(monkeypatch, tmp_path):
    fake_segment_1 = MagicMock(start=0.0, end=1.2, text=" Selamat pagi")
    fake_segment_2 = MagicMock(start=1.2, end=2.5, text=" mari kita mulai")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment_1, fake_segment_2], MagicMock())

    monkeypatch.setattr(
        "app.asr.cuda_backend.WhisperModel",
        lambda *args, **kwargs: fake_model,
    )

    backend = CudaWhisperBackend()
    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path, language="id")

    fake_model.transcribe.assert_called_once_with(str(wav_path), language="id")
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 1200
    assert segments[0].text == "Selamat pagi"
    assert segments[1].text == "mari kita mulai"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/asr/test_base.py tests/asr/test_cuda_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.asr.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/asr/base.py
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TranscriptSegmentResult:
    start_ms: int
    end_ms: int
    text: str


class TranscriberBackend(Protocol):
    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        ...
```

```python
# app/asr/cuda_backend.py
from pathlib import Path

from faster_whisper import WhisperModel

from app.asr.base import TranscriptSegmentResult


class CudaWhisperBackend:
    def __init__(self, model_size: str = "large-v3", device: str = "cuda", compute_type: str = "float16"):
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        segments, _info = self._model.transcribe(str(wav_path), language=language)
        return [
            TranscriptSegmentResult(
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                text=seg.text.strip(),
            )
            for seg in segments
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/asr/test_base.py tests/asr/test_cuda_backend.py -v`
Expected: PASS

- [ ] **Step 5: Install faster-whisper and commit**

```bash
./.venv/Scripts/python.exe -m pip install faster-whisper
git add pyproject.toml app/asr/base.py app/asr/cuda_backend.py tests/asr/test_base.py tests/asr/test_cuda_backend.py
git commit -m "feat: add TranscriberBackend interface and faster-whisper CUDA backend"
```

- [ ] **Step 6 (manual, hardware-dependent, run only on the GTX 1080 Ti machine): real smoke test**

```bash
./.venv/Scripts/python.exe -c "
from pathlib import Path
from app.asr.cuda_backend import CudaWhisperBackend

backend = CudaWhisperBackend(model_size='small')  # small for a quick manual check
segments = backend.transcribe(Path('tests/fixtures/sample_id.wav'))
for s in segments:
    print(s.start_ms, s.end_ms, s.text)
"
```
Expected: prints recognizable Indonesian text segments (requires a real `.wav`
fixture — record one manually and drop it at `tests/fixtures/sample_id.wav`
before running this step; not part of the automated suite).

---

### Task 8: OpenVINO ASR Backend

**Files:**
- Create: `app/asr/openvino_backend.py`
- Test: `tests/asr/test_openvino_backend.py`

**Interfaces:**
- Consumes: `app.asr.base.TranscriptSegmentResult` (Task 7).
- Produces: `app.asr.openvino_backend.OpenVinoWhisperBackend(model_size: str = "large-v3", device: str = "GPU")` implementing `TranscriberBackend`, using `optimum-intel`'s `OVModelForSpeechSeq2Seq` + `transformers.WhisperProcessor`.

- [ ] **Step 1: Write the failing test**

```python
# tests/asr/test_openvino_backend.py
from unittest.mock import MagicMock

import numpy as np

from app.asr.openvino_backend import OpenVinoWhisperBackend


def test_transcribe_maps_whisper_output_to_segments(monkeypatch, tmp_path):
    fake_model = MagicMock()
    fake_model.generate.return_value = MagicMock()

    fake_processor = MagicMock()
    fake_processor.return_value.input_features = MagicMock()
    fake_processor.batch_decode.return_value = ["Selamat pagi mari kita mulai"]

    monkeypatch.setattr(
        "app.asr.openvino_backend.OVModelForSpeechSeq2Seq.from_pretrained",
        lambda *args, **kwargs: fake_model,
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend.WhisperProcessor.from_pretrained",
        lambda *args, **kwargs: fake_processor,
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend._load_audio_array",
        lambda wav_path: (np.zeros(16000, dtype=np.float32), 16000),
    )

    backend = OpenVinoWhisperBackend()
    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path, language="id")

    assert len(segments) == 1
    assert segments[0].text == "Selamat pagi mari kita mulai"
    assert segments[0].start_ms == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/asr/test_openvino_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.asr.openvino_backend'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/asr/openvino_backend.py
from pathlib import Path

import numpy as np
from optimum.intel.openvino import OVModelForSpeechSeq2Seq
from transformers import WhisperProcessor

from app.asr.base import TranscriptSegmentResult


def _load_audio_array(wav_path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    audio, samplerate = sf.read(str(wav_path), dtype="float32")
    return audio, samplerate


class OpenVinoWhisperBackend:
    def __init__(self, model_size: str = "large-v3", device: str = "GPU"):
        model_id = f"openai/whisper-{model_size}"
        self._model = OVModelForSpeechSeq2Seq.from_pretrained(model_id, export=True, device=device)
        self._processor = WhisperProcessor.from_pretrained(model_id)

    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        audio, samplerate = _load_audio_array(wav_path)
        inputs = self._processor(audio, sampling_rate=samplerate, return_tensors="pt")
        predicted_ids = self._model.generate(inputs.input_features, language=language)
        text = self._processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        duration_ms = int(len(audio) / samplerate * 1000)
        return [TranscriptSegmentResult(start_ms=0, end_ms=duration_ms, text=text.strip())]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/asr/test_openvino_backend.py -v`
Expected: PASS

- [ ] **Step 5: Install deps and commit**

```bash
./.venv/Scripts/python.exe -m pip install "optimum[openvino]" soundfile
git add pyproject.toml app/asr/openvino_backend.py tests/asr/test_openvino_backend.py
git commit -m "feat: add OpenVINO (Intel GPU/NPU) whisper backend"
```

Note: this backend does not segment on its own (single full-file decode, no
per-segment timestamps) — good enough for Fase 1 batch transcription of mic
and speaker files separately; per-utterance segmentation for the OpenVINO
path can be added later if needed once real hardware testing shows it matters.

---

### Task 9: Speaker Diarization

**Files:**
- Create: `app/diarization/__init__.py`
- Create: `app/diarization/diarizer.py`
- Test: `tests/diarization/test_diarizer.py`
- Create: `tests/diarization/__init__.py`

**Interfaces:**
- Produces:
  - `app.diarization.diarizer.SpeakerSegment` (dataclass: `start_ms: int, end_ms: int, label: str`)
  - `app.diarization.diarizer.Diarizer(hf_token: str, device: str = "cpu")` with `diarize(self, wav_path: Path) -> list[SpeakerSegment]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/diarization/test_diarizer.py
from unittest.mock import MagicMock

from app.diarization.diarizer import Diarizer, SpeakerSegment


def test_diarize_maps_pyannote_turns_to_speaker_segments(monkeypatch, tmp_path):
    fake_turn_1 = MagicMock(start=0.0, end=2.0)
    fake_turn_2 = MagicMock(start=2.0, end=4.5)

    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = [
        (fake_turn_1, None, "SPEAKER_00"),
        (fake_turn_2, None, "SPEAKER_01"),
    ]

    fake_pipeline = MagicMock()
    fake_pipeline.return_value = fake_annotation

    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    wav_path = tmp_path / "speaker.wav"
    wav_path.touch()
    segments = diarizer.diarize(wav_path)

    assert segments == [
        SpeakerSegment(start_ms=0, end_ms=2000, label="Speaker 1"),
        SpeakerSegment(start_ms=2000, end_ms=4500, label="Speaker 2"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/diarization/test_diarizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.diarization'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/diarization/__init__.py
```

```python
# app/diarization/diarizer.py
from dataclasses import dataclass
from pathlib import Path

from pyannote.audio import Pipeline


@dataclass
class SpeakerSegment:
    start_ms: int
    end_ms: int
    label: str


class Diarizer:
    def __init__(self, hf_token: str, device: str = "cpu"):
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
        )
        self._device = device

    def diarize(self, wav_path: Path) -> list[SpeakerSegment]:
        annotation = self._pipeline(str(wav_path))
        speaker_numbers: dict[str, int] = {}
        segments = []
        for turn, _, raw_label in annotation.itertracks(yield_label=True):
            if raw_label not in speaker_numbers:
                speaker_numbers[raw_label] = len(speaker_numbers) + 1
            segments.append(SpeakerSegment(
                start_ms=int(turn.start * 1000),
                end_ms=int(turn.end * 1000),
                label=f"Speaker {speaker_numbers[raw_label]}",
            ))
        return segments
```

```python
# tests/diarization/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/diarization/test_diarizer.py -v`
Expected: PASS

- [ ] **Step 5: Install pyannote.audio and commit**

```bash
./.venv/Scripts/python.exe -m pip install pyannote.audio
git add pyproject.toml app/diarization/__init__.py app/diarization/diarizer.py tests/diarization/__init__.py tests/diarization/test_diarizer.py
git commit -m "feat: add pyannote.audio speaker diarization wrapper"
```

---

### Task 10: Transcript + Speaker Merge Logic

**Files:**
- Create: `app/pipeline/__init__.py`
- Create: `app/pipeline/merge.py`
- Test: `tests/pipeline/test_merge.py`
- Create: `tests/pipeline/__init__.py`

**Interfaces:**
- Consumes: `app.asr.base.TranscriptSegmentResult` (Task 7), `app.diarization.diarizer.SpeakerSegment` (Task 9).
- Produces:
  - `app.pipeline.merge.MergedSegment` (dataclass: `source: str, speaker_label: str, start_ms: int, end_ms: int, text: str`)
  - `app.pipeline.merge.merge_segments(mic_segments: list[TranscriptSegmentResult], speaker_segments: list[TranscriptSegmentResult], speaker_labels: list[SpeakerSegment]) -> list[MergedSegment]`

Merge rule: every `mic_segments` entry becomes a `MergedSegment` with
`source="mic"`, `speaker_label="Anda"`. Every `speaker_segments` entry is
matched against `speaker_labels` by maximum time overlap; if no
`speaker_labels` entry overlaps at all, `speaker_label="Speaker ?"`. Result
sorted by `start_ms` ascending.

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_merge.py
from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment
from app.pipeline.merge import MergedSegment, merge_segments


def test_merge_labels_mic_as_anda_and_matches_speaker_by_overlap():
    mic_segments = [TranscriptSegmentResult(start_ms=0, end_ms=800, text="Selamat pagi")]
    speaker_segments = [
        TranscriptSegmentResult(start_ms=900, end_ms=2000, text="Pagi, mulai ya"),
        TranscriptSegmentResult(start_ms=2100, end_ms=3000, text="Siap"),
    ]
    speaker_labels = [
        SpeakerSegment(start_ms=850, end_ms=2050, label="Speaker 1"),
        SpeakerSegment(start_ms=2050, end_ms=3200, label="Speaker 2"),
    ]

    merged = merge_segments(mic_segments, speaker_segments, speaker_labels)

    assert merged == [
        MergedSegment(source="mic", speaker_label="Anda", start_ms=0, end_ms=800, text="Selamat pagi"),
        MergedSegment(source="speaker", speaker_label="Speaker 1", start_ms=900, end_ms=2000, text="Pagi, mulai ya"),
        MergedSegment(source="speaker", speaker_label="Speaker 2", start_ms=2100, end_ms=3000, text="Siap"),
    ]


def test_speaker_segment_with_no_overlap_gets_unknown_label():
    speaker_segments = [TranscriptSegmentResult(start_ms=5000, end_ms=6000, text="halo")]
    merged = merge_segments([], speaker_segments, [])
    assert merged[0].speaker_label == "Speaker ?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/pipeline/test_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/pipeline/__init__.py
```

```python
# app/pipeline/merge.py
from dataclasses import dataclass

from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment


@dataclass
class MergedSegment:
    source: str
    speaker_label: str
    start_ms: int
    end_ms: int
    text: str


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _best_label(segment: TranscriptSegmentResult, speaker_labels: list[SpeakerSegment]) -> str:
    best_label = "Speaker ?"
    best_overlap = 0
    for candidate in speaker_labels:
        overlap = _overlap_ms(segment.start_ms, segment.end_ms, candidate.start_ms, candidate.end_ms)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = candidate.label
    return best_label


def merge_segments(
    mic_segments: list[TranscriptSegmentResult],
    speaker_segments: list[TranscriptSegmentResult],
    speaker_labels: list[SpeakerSegment],
) -> list[MergedSegment]:
    merged = [
        MergedSegment(source="mic", speaker_label="Anda", start_ms=s.start_ms, end_ms=s.end_ms, text=s.text)
        for s in mic_segments
    ]
    merged += [
        MergedSegment(
            source="speaker", speaker_label=_best_label(s, speaker_labels),
            start_ms=s.start_ms, end_ms=s.end_ms, text=s.text,
        )
        for s in speaker_segments
    ]
    merged.sort(key=lambda seg: seg.start_ms)
    return merged
```

```python
# tests/pipeline/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/pipeline/test_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/__init__.py app/pipeline/merge.py tests/pipeline/__init__.py tests/pipeline/test_merge.py
git commit -m "feat: add transcript+speaker merge logic"
```

---

### Task 11: Groq Summarizer (MoM Generation)

**Files:**
- Create: `app/summarization/__init__.py`
- Create: `app/summarization/groq_client.py`
- Test: `tests/summarization/test_groq_client.py`
- Create: `tests/summarization/__init__.py`

**Interfaces:**
- Produces:
  - `app.summarization.groq_client.MomResult` (dataclass: `minute_by_minute: list[dict], decisions: list[str], action_items: list[dict], detailed_notes: str`)
  - `app.summarization.groq_client.GroqSummarizer(api_key: str, model: str = "llama-3.3-70b-versatile")` with `summarize(self, meeting_title: str, transcript_text: str) -> MomResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/summarization/test_groq_client.py
import json
from unittest.mock import MagicMock

from app.summarization.groq_client import GroqSummarizer, MomResult


def test_summarize_parses_json_response(monkeypatch):
    fake_mom = {
        "minute_by_minute": [{"time": "00:00", "point": "Pembukaan rapat"}],
        "decisions": ["Rilis ditunda ke minggu depan"],
        "action_items": [{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}],
        "detailed_notes": "Rapat membahas kesiapan rilis.",
    }
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=json.dumps(fake_mom)))]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    monkeypatch.setattr(
        "app.summarization.groq_client.Groq",
        lambda api_key: fake_client,
    )

    summarizer = GroqSummarizer(api_key="fake-key")
    result = summarizer.summarize("Rapat Rilis", "Anda: halo semua\nSpeaker 1: mari mulai")

    assert result == MomResult(
        minute_by_minute=[{"time": "00:00", "point": "Pembukaan rapat"}],
        decisions=["Rilis ditunda ke minggu depan"],
        action_items=[{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}],
        detailed_notes="Rapat membahas kesiapan rilis.",
    )
    fake_client.chat.completions.create.assert_called_once()
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "llama-3.3-70b-versatile"
    assert call_kwargs["response_format"] == {"type": "json_object"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/summarization/test_groq_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.summarization'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/summarization/__init__.py
```

```python
# app/summarization/groq_client.py
import json
from dataclasses import dataclass

from groq import Groq

_PROMPT_TEMPLATE = """\
Kamu adalah asisten yang membuat Minutes of Meeting (MoM) dalam Bahasa \
Indonesia dari transkrip rapat berikut. Judul rapat: "{title}".

Transkrip:
{transcript}

Balas HANYA dengan JSON valid persis dengan struktur ini, tanpa teks lain:
{{
  "minute_by_minute": [{{"time": "mm:ss", "point": "..."}}],
  "decisions": ["..."],
  "action_items": [{{"item": "...", "assignee": "...", "due": "..."}}],
  "detailed_notes": "catatan detail dan lengkap dalam Bahasa Indonesia"
}}
"""


@dataclass
class MomResult:
    minute_by_minute: list[dict]
    decisions: list[str]
    action_items: list[dict]
    detailed_notes: str


class GroqSummarizer:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self._client = Groq(api_key=api_key)
        self._model = model

    def summarize(self, meeting_title: str, transcript_text: str) -> MomResult:
        prompt = _PROMPT_TEMPLATE.format(title=meeting_title, transcript=transcript_text)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return MomResult(
            minute_by_minute=data["minute_by_minute"],
            decisions=data["decisions"],
            action_items=data["action_items"],
            detailed_notes=data["detailed_notes"],
        )
```

```python
# tests/summarization/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/summarization/test_groq_client.py -v`
Expected: PASS

- [ ] **Step 5: Install groq and commit**

```bash
./.venv/Scripts/python.exe -m pip install groq
git add pyproject.toml app/summarization/__init__.py app/summarization/groq_client.py tests/summarization/__init__.py tests/summarization/test_groq_client.py
git commit -m "feat: add Groq-based MoM summarizer"
```

---

### Task 12: MoM .docx Export

**Files:**
- Create: `app/summarization/docx_export.py`
- Test: `tests/summarization/test_docx_export.py`

**Interfaces:**
- Consumes: `app.summarization.groq_client.MomResult` (Task 11).
- Produces: `app.summarization.docx_export.export_mom_docx(meeting_title: str, meeting_date: datetime, mom: MomResult, output_path: Path) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/summarization/test_docx_export.py
from datetime import datetime

from docx import Document

from app.summarization.docx_export import export_mom_docx
from app.summarization.groq_client import MomResult


def test_export_creates_docx_with_expected_sections(tmp_path):
    mom = MomResult(
        minute_by_minute=[{"time": "00:00", "point": "Pembukaan"}],
        decisions=["Lanjutkan rencana A"],
        action_items=[{"item": "Kirim laporan", "assignee": "Budi", "due": "2026-08-01"}],
        detailed_notes="Semua peserta setuju melanjutkan.",
    )
    output_path = tmp_path / "mom.docx"

    result_path = export_mom_docx("Rapat Mingguan", datetime(2026, 7, 30, 9, 0), mom, output_path)

    assert result_path == output_path
    assert output_path.exists()

    doc = Document(str(output_path))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Rapat Mingguan" in full_text
    assert "Ringkasan Menit ke Menit" in full_text
    assert "Keputusan" in full_text
    assert "Action Items" in full_text
    assert "Catatan Detail" in full_text
    assert "Lanjutkan rencana A" in full_text
    assert "Semua peserta setuju melanjutkan." in full_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/summarization/test_docx_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.summarization.docx_export'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/summarization/docx_export.py
from datetime import datetime
from pathlib import Path

from docx import Document

from app.summarization.groq_client import MomResult


def export_mom_docx(meeting_title: str, meeting_date: datetime, mom: MomResult, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()

    doc.add_heading(meeting_title, level=0)
    doc.add_paragraph(f"Tanggal: {meeting_date.strftime('%d %B %Y %H:%M')}")

    doc.add_heading("Ringkasan Menit ke Menit", level=1)
    for entry in mom.minute_by_minute:
        doc.add_paragraph(f"{entry['time']} — {entry['point']}", style="List Bullet")

    doc.add_heading("Keputusan", level=1)
    for decision in mom.decisions:
        doc.add_paragraph(decision, style="List Bullet")

    doc.add_heading("Action Items", level=1)
    table = doc.add_table(rows=1, cols=3)
    header = table.rows[0].cells
    header[0].text, header[1].text, header[2].text = "Item", "PIC", "Tenggat"
    for action in mom.action_items:
        row = table.add_row().cells
        row[0].text = action["item"]
        row[1].text = action["assignee"]
        row[2].text = action["due"]

    doc.add_heading("Catatan Detail", level=1)
    doc.add_paragraph(mom.detailed_notes)

    doc.save(str(output_path))
    return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/summarization/test_docx_export.py -v`
Expected: PASS

- [ ] **Step 5: Install python-docx and commit**

```bash
./.venv/Scripts/python.exe -m pip install python-docx
git add pyproject.toml app/summarization/docx_export.py tests/summarization/test_docx_export.py
git commit -m "feat: add MoM .docx export"
```

---

### Task 13: Finalize Pipeline (Batch Orchestration)

**Files:**
- Create: `app/pipeline/finalize.py`
- Test: `tests/pipeline/test_finalize.py`

**Interfaces:**
- Consumes: `app.storage.repository.*` (Task 3), `app.asr.detect.detect_backend` (Task 6), `app.asr.base.TranscriberBackend` (Task 7), `app.diarization.diarizer.Diarizer` (Task 9), `app.pipeline.merge.merge_segments` (Task 10), `app.summarization.groq_client.GroqSummarizer` (Task 11), `app.summarization.docx_export.export_mom_docx` (Task 12).
- Produces: `app.pipeline.finalize.finalize_meeting(session, meeting_id: int, meeting_title: str, meeting_date: datetime, mic_wav: Path, speaker_wav: Path, transcriber: TranscriberBackend, diarizer, summarizer: GroqSummarizer, docx_output_path: Path) -> Summary`. Backend/diarizer/summarizer are passed in (constructed by the caller using `detect_backend()` + settings) so this function stays fully unit-testable with fakes — no hidden hardware/network access inside it.

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_finalize.py
import asyncio
from datetime import datetime

from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment
from app.storage.db import make_engine, init_db, make_session_factory
from app.storage import repository as repo
from app.summarization.groq_client import MomResult
from app.pipeline.finalize import finalize_meeting


class FakeTranscriber:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, wav_path, language="id"):
        return self._segments


class FakeDiarizer:
    def __init__(self, labels):
        self._labels = labels

    def diarize(self, wav_path):
        return self._labels


class FakeSummarizer:
    def summarize(self, meeting_title, transcript_text):
        assert "Anda" in transcript_text
        assert "Speaker 1" in transcript_text
        return MomResult(
            minute_by_minute=[{"time": "00:00", "point": "Mulai"}],
            decisions=["Lanjut"],
            action_items=[],
            detailed_notes="Catatan.",
        )


def test_finalize_meeting_saves_segments_and_summary(tmp_path):
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
        docx_path = tmp_path / "mom.docx"

        transcriber_calls = {"mic.wav": [
            TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")
        ], "speaker.wav": [
            TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")
        ]}

        class RoutingFakeTranscriber:
            def transcribe(self, wav_path, language="id"):
                return transcriber_calls[wav_path.name]

        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])
        summarizer = FakeSummarizer()

        async with session_factory() as session:
            summary = await finalize_meeting(
                session=session,
                meeting_id=meeting_id,
                meeting_title="Rapat Uji",
                meeting_date=datetime(2026, 7, 30, 9, 0),
                mic_wav=mic_wav,
                speaker_wav=speaker_wav,
                transcriber=RoutingFakeTranscriber(),
                diarizer=diarizer,
                summarizer=summarizer,
                docx_output_path=docx_path,
            )
            await session.commit()

        async with session_factory() as session:
            meetings = await repo.list_meetings(session)
        return summary, meetings

    summary, meetings = asyncio.run(scenario())
    assert summary.status == "ready"
    assert meetings[0].status == "completed"
    assert (tmp_path / "mom.docx").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/pipeline/test_finalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.finalize'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/pipeline/finalize.py
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.asr.base import TranscriberBackend
from app.pipeline.merge import merge_segments
from app.storage import repository as repo
from app.storage.models import Summary
from app.summarization.docx_export import export_mom_docx
from app.summarization.groq_client import GroqSummarizer


async def finalize_meeting(
    session: AsyncSession,
    meeting_id: int,
    meeting_title: str,
    meeting_date: datetime,
    mic_wav: Path,
    speaker_wav: Path,
    transcriber: TranscriberBackend,
    diarizer,
    summarizer: GroqSummarizer,
    docx_output_path: Path,
) -> Summary:
    try:
        mic_segments = transcriber.transcribe(mic_wav, language="id")
        speaker_segments = transcriber.transcribe(speaker_wav, language="id")
        speaker_labels = diarizer.diarize(speaker_wav)
        merged = merge_segments(mic_segments, speaker_segments, speaker_labels)

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
        await repo.save_transcript_segments(session, segment_rows)

        transcript_text = "\n".join(f"{seg.speaker_label}: {seg.text}" for seg in merged)
        mom = summarizer.summarize(meeting_title, transcript_text)
        docx_path = export_mom_docx(meeting_title, meeting_date, mom, docx_output_path)

        import json
        mom_json = json.dumps({
            "minute_by_minute": mom.minute_by_minute,
            "decisions": mom.decisions,
            "action_items": mom.action_items,
            "detailed_notes": mom.detailed_notes,
        })
        summary = await repo.save_summary(
            session, meeting_id, mom_json=mom_json, docx_path=str(docx_path),
            groq_model="llama-3.3-70b-versatile", status="ready",
        )
        await repo.mark_meeting_status(session, meeting_id, "completed")
        return summary
    except Exception:
        await repo.mark_meeting_status(session, meeting_id, "failed")
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/pipeline/test_finalize.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/finalize.py tests/pipeline/test_finalize.py
git commit -m "feat: add finalize_meeting batch orchestration pipeline"
```

---

### Task 14: Recorder Controller (Start/Stop State Machine)

**Files:**
- Create: `app/ui/__init__.py`
- Create: `app/ui/controller.py`
- Test: `tests/ui/test_controller.py`
- Create: `tests/ui/__init__.py`

**Interfaces:**
- Consumes: `app.audio.capture.MicSpeakerRecorder` (Task 5), `app.storage.repository.*` (Task 3), `app.pipeline.finalize.finalize_meeting` (Task 13).
- Produces: `app.ui.controller.RecorderController(session_factory, recorder_factory, finalize_fn, recordings_dir: Path)` with:
  - `start_meeting(self, title: str) -> int` — starts the recorder FIRST (against a UUID-named staging folder), and only creates the DB meeting row if that succeeds, so a missing/broken audio device never leaves an empty meeting row behind. Re-raises the recorder's exception after setting `state="error"` and `error_message`.
  - `stop_meeting(self) -> None` (stops recorder, runs `finalize_fn` synchronously against the just-recorded files; UI layer is responsible for calling this off the Tkinter main thread)
  - `state: str` property, one of `"idle"`, `"recording"`, `"processing"`, `"done"`, `"error"`
  - `error_message: str | None` — set when `state == "error"`

`recorder_factory: Callable[[Path, Path], MicSpeakerRecorderProtocol]` and
`finalize_fn: Callable[..., Awaitable[Summary]]` are injected so the
controller has zero direct hardware/network/DB-driver dependencies of its
own — fully testable with fakes.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_controller.py
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
                        groq_model="llama-3.3-70b-versatile", status="ready")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ui/test_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/ui/__init__.py
```

```python
# app/ui/controller.py
import asyncio
import uuid
import wave
from datetime import datetime
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
    ):
        self._session_factory = session_factory
        self._recorder_factory = recorder_factory
        self._finalize_fn = finalize_fn
        self._recordings_dir = recordings_dir
        self.state = "idle"
        self.error_message: str | None = None
        self._meeting_id: int | None = None
        self._meeting_title: str | None = None
        self._recorder = None

    def start_meeting(self, title: str) -> int:
        # Try the recorder against a UUID-named staging folder BEFORE touching
        # the DB at all, so a missing/broken audio device never leaves behind
        # an empty meeting row (spec requirement).
        session_dirname = uuid.uuid4().hex
        meeting_dir = self._recordings_dir / session_dirname
        mic_path = meeting_dir / "mic.wav"
        speaker_path = meeting_dir / "speaker.wav"
        recorder = self._recorder_factory(mic_path, speaker_path)

        try:
            recorder.start()
        except Exception as exc:
            self.error_message = f"Gagal memulai rekam (cek perangkat mic/speaker): {exc}"
            self.state = "error"
            raise

        async def _create():
            async with self._session_factory() as session:
                meeting = await repo.create_meeting(session, title, None)
                await repo.start_recording(session, meeting.id)
                await session.commit()
                return meeting.id

        meeting_id = asyncio.run(_create())
        self._meeting_id = meeting_id
        self._meeting_title = title
        self._recorder = recorder
        self.state = "recording"
        return meeting_id

    def stop_meeting(self) -> None:
        mic_path, speaker_path = self._recorder.stop()
        self.state = "processing"

        async def _finalize():
            async with self._session_factory() as session:
                await repo.stop_recording(session, self._meeting_id)
                await repo.save_recording_file(
                    session, self._meeting_id, str(mic_path), "mic", _wav_duration_ms(mic_path)
                )
                await repo.save_recording_file(
                    session, self._meeting_id, str(speaker_path), "speaker", _wav_duration_ms(speaker_path)
                )
                await self._finalize_fn(
                    session=session,
                    meeting_id=self._meeting_id,
                    meeting_title=self._meeting_title,
                    meeting_date=datetime.now(),
                    mic_wav=mic_path,
                    speaker_wav=speaker_path,
                )
                await session.commit()

        try:
            asyncio.run(_finalize())
            self.state = "done"
        except Exception:
            self.state = "error"
            raise
```

```python
# tests/ui/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ui/test_controller.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/__init__.py app/ui/controller.py tests/ui/__init__.py tests/ui/test_controller.py
git commit -m "feat: add recorder controller state machine"
```

---

### Task 15: Tkinter Main Window

**Files:**
- Create: `app/ui/window.py`
- Test: `tests/ui/test_window.py`

**Interfaces:**
- Consumes: `app.ui.controller.RecorderController` (Task 14).
- Produces: `app.ui.window.MainWindow(root: tk.Tk, controller: RecorderController)` with `refresh_status(self) -> None` (updates a status label from `controller.state`) and `on_start_clicked(self, title: str) -> None` / `on_stop_clicked(self) -> None` wired to buttons. No real Tkinter event loop is exercised in the automated test — `tkinter.Tk()` works headless enough on Windows CI for widget construction, but to keep the fast suite portable we test `MainWindow`'s button handlers directly against a fake controller instead of driving real GUI events.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_window.py
import tkinter as tk

import pytest

from app.ui.window import MainWindow


class FakeController:
    def __init__(self):
        self.state = "idle"
        self.started_with = None
        self.stopped = False

    def start_meeting(self, title):
        self.started_with = title
        self.state = "recording"
        return 1

    def stop_meeting(self):
        self.stopped = True
        self.state = "done"


def _tk_available() -> bool:
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_start_and_stop_buttons_call_controller():
    root = tk.Tk()
    controller = FakeController()
    window = MainWindow(root, controller)

    window.on_start_clicked("Rapat Sore")
    assert controller.started_with == "Rapat Sore"
    assert "recording" in window.status_var.get().lower() or controller.state == "recording"

    window.on_stop_clicked()
    assert controller.stopped is True

    root.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ui/test_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui.window'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/ui/window.py
import tkinter as tk
from tkinter import scrolledtext

from app.ui.controller import RecorderController

_STATUS_LABELS = {
    "idle": "Siap",
    "recording": "Sedang merekam...",
    "processing": "Memproses transkrip & MoM...",
    "done": "Selesai",
    "error": "Gagal, lihat log",
}


class MainWindow:
    def __init__(self, root: tk.Tk, controller: RecorderController):
        self._root = root
        self._controller = controller
        self._root.title("Meeting Recorder")

        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value=_STATUS_LABELS["idle"])

        tk.Label(root, text="Judul Meeting:").pack(anchor="w")
        tk.Entry(root, textvariable=self.title_var, width=40).pack(fill="x")

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", pady=4)
        tk.Button(button_frame, text="Mulai Rekam", command=self._handle_start).pack(side="left")
        tk.Button(button_frame, text="Stop Rekam", command=self._handle_stop).pack(side="left")

        tk.Label(root, textvariable=self.status_var).pack(anchor="w")
        self.transcript_view = scrolledtext.ScrolledText(root, height=15, width=60)
        self.transcript_view.pack(fill="both", expand=True)

    def _handle_start(self) -> None:
        self.on_start_clicked(self.title_var.get())

    def _handle_stop(self) -> None:
        self.on_stop_clicked()

    def on_start_clicked(self, title: str) -> None:
        self._controller.start_meeting(title)
        self.refresh_status()

    def on_stop_clicked(self) -> None:
        self._controller.stop_meeting()
        self.refresh_status()

    def refresh_status(self) -> None:
        self.status_var.set(_STATUS_LABELS.get(self._controller.state, self._controller.state))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ui/test_window.py -v`
Expected: PASS (or SKIPPED if run headless without a display — acceptable,
verify manually on the real desktop/laptop per Step 5)

- [ ] **Step 5: Manual smoke test on the real machine**

```bash
./.venv/Scripts/python.exe -c "
import tkinter as tk
from app.ui.controller import RecorderController
from app.ui.window import MainWindow
# construct with real dependencies wired in main.py (Task 16), open window,
# click Mulai Rekam / Stop Rekam manually, confirm status label updates.
"
```

- [ ] **Step 6: Commit**

```bash
git add app/ui/window.py tests/ui/test_window.py
git commit -m "feat: add Tkinter main window for meeting control"
```

---

### Task 16: Tray Icon + App Entrypoint

**Files:**
- Create: `app/tray/__init__.py`
- Create: `app/tray/icon.py`
- Create: `app/main.py`
- Test: `tests/tray/test_icon.py`
- Create: `tests/tray/__init__.py`

**Interfaces:**
- Consumes: `app.ui.window.MainWindow` (Task 15).
- Produces: `app.tray.icon.build_tray_icon(on_show: Callable[[], None], on_quit: Callable[[], None]) -> pystray.Icon`. `app/main.py` is the real entrypoint (`python -m app.main`) wiring config → DB engine → `detect_backend()` → concrete `CudaWhisperBackend`/`OpenVinoWhisperBackend` → `Diarizer` → `GroqSummarizer` → `RecorderController` → `MainWindow` → tray icon; not unit-tested directly (it's pure wiring), verified by the Task 16 manual smoke test.

- [ ] **Step 1: Write the failing test**

```python
# tests/tray/test_icon.py
from app.tray.icon import build_tray_icon


def test_build_tray_icon_has_show_and_quit_menu_items():
    shown = []
    quit_called = []

    icon = build_tray_icon(on_show=lambda: shown.append(True), on_quit=lambda: quit_called.append(True))

    assert icon.title == "Meeting Recorder"
    item_texts = [item.text for item in icon.menu.items]
    assert any("Buka" in t for t in item_texts)
    assert any("Keluar" in t for t in item_texts)

    for item in icon.menu.items:
        if "Buka" in item.text:
            item.action(icon, item)
        if "Keluar" in item.text:
            item.action(icon, item)

    assert shown == [True]
    assert quit_called == [True]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/tray/test_icon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tray'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/tray/__init__.py
```

```python
# app/tray/icon.py
from typing import Callable

import pystray
from PIL import Image, ImageDraw


def _default_image():
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill="red")
    return image


def build_tray_icon(on_show: Callable[[], None], on_quit: Callable[[], None]) -> pystray.Icon:
    def _show(icon, item):
        on_show()

    def _quit(icon, item):
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Buka Dashboard", _show),
        pystray.MenuItem("Keluar", _quit),
    )
    return pystray.Icon("meeting-recorder", _default_image(), "Meeting Recorder", menu)
```

```python
# tests/tray/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/tray/test_icon.py -v`
Expected: PASS

- [ ] **Step 5: Write the real entrypoint**

```python
# app/main.py
import tkinter as tk
from pathlib import Path

from app.asr.cuda_backend import CudaWhisperBackend
from app.asr.detect import detect_backend
from app.asr.openvino_backend import OpenVinoWhisperBackend
from app.config import get_settings
from app.diarization.diarizer import Diarizer
from app.pipeline.finalize import finalize_meeting
from app.storage.db import init_db, make_engine, make_session_factory
from app.summarization.groq_client import GroqSummarizer
from app.tray.icon import build_tray_icon
from app.ui.controller import RecorderController
from app.ui.window import MainWindow


def build_transcriber(backend_name: str):
    if backend_name == "cuda":
        return CudaWhisperBackend()
    if backend_name == "openvino":
        return OpenVinoWhisperBackend()
    return CudaWhisperBackend(device="cpu", compute_type="int8")


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    import asyncio
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    backend_name = detect_backend(settings.asr_backend_override)
    transcriber = build_transcriber(backend_name)
    diarizer = Diarizer(hf_token=settings.hf_token)
    summarizer = GroqSummarizer(api_key=settings.groq_api_key)

    async def finalize_fn(**kwargs):
        docx_path = settings.recordings_dir / str(kwargs["meeting_id"]) / "mom.docx"
        return await finalize_meeting(
            transcriber=transcriber, diarizer=diarizer, summarizer=summarizer,
            docx_output_path=docx_path, **kwargs,
        )

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: _real_recorder(mic, speaker),
        finalize_fn=finalize_fn,
        recordings_dir=settings.recordings_dir,
    )

    root = tk.Tk()
    window = MainWindow(root, controller)

    def show_window():
        root.deiconify()

    def quit_app():
        root.quit()

    icon = build_tray_icon(on_show=show_window, on_quit=quit_app)

    import threading
    threading.Thread(target=icon.run, daemon=True).start()
    root.mainloop()


def _real_recorder(mic_path: Path, speaker_path: Path):
    from app.audio.capture import MicSpeakerRecorder
    return MicSpeakerRecorder(mic_path, speaker_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Install pystray/pillow and commit**

```bash
./.venv/Scripts/python.exe -m pip install pystray pillow
git add pyproject.toml app/tray/__init__.py app/tray/icon.py app/main.py tests/tray/__init__.py tests/tray/test_icon.py
git commit -m "feat: add tray icon and wire real application entrypoint"
```

- [ ] **Step 7: Full manual smoke test (real hardware, both machines eventually)**

Run: `./.venv/Scripts/python.exe -m app.main`

Expected: tray icon appears, Tkinter window opens, clicking "Mulai Rekam" with
a title starts capturing mic+speaker to `./recordings/<id>/`, clicking "Stop
Rekam" transcribes+diarizes+summarizes and produces
`./recordings/<id>/mom.docx`, and a row appears in the `meeting_recorder`
Postgres database's `meetings`/`summaries` tables with `status="completed"`.

---

## Post-Plan Note

This plan covers Fase 1 only (spec §11). Fase 2 (live small-model preview +
rolling-buffer diarization streamed into the Tkinter window) and Fase 3
(speaker rename UI, meeting history browser, retry-failed-summary UI) are
out of scope here and should get their own plans once Fase 1 is verified
working end-to-end on both the GTX 1080 Ti desktop and the Core Ultra 7 155H
laptop.
