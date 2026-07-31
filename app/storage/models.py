from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    scheduled_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Set once at creation so a meeting still "recording"/"processing" after a
    # crash can be found again on restart -- Recording rows only get written
    # at Stop, which never happened for an abandoned meeting.
    recording_dir: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)
    failed_stage: Mapped[str | None] = mapped_column(default=None)
    device_id: Mapped[str | None] = mapped_column(default=None)
    device_label: Mapped[str | None] = mapped_column(default=None)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    meeting: Mapped["Meeting"] = relationship(back_populates="summary")
