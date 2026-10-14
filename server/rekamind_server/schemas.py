"""Pydantic models: the LLM extraction contract and the API's response shapes."""

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---- LLM extraction contract -------------------------------------------------
# `ExtractionResult.model_json_schema()` is what a structured-output LLM call is
# constrained to, so malformed JSON is rejected at the provider instead of being
# discovered later in a KeyError.

_CLOCK = re.compile(r"\[?(?:(\d+):)?(\d{1,2}):(\d{2})\]?")


def parse_clock(text: str | None) -> int | None:
    """'05:30' or '1:02:03' (optionally in brackets) -> milliseconds."""
    if not text or not (m := _CLOCK.fullmatch(text.strip())):
        return None
    h, mi, se = int(m[1] or 0), int(m[2]), int(m[3])
    return ((h * 60 + mi) * 60 + se) * 1000


class ExtractedTask(BaseModel):
    title: str = Field(min_length=3, max_length=200, description="Imperative, one line")
    description: str = ""
    assignee: str | None = Field(default=None, description="Name exactly as spoken; null if nobody was assigned")
    deadline_text: str | None = Field(default=None, description="Deadline phrase exactly as spoken, e.g. 'Jumat depan'")
    estimate_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 90)
    priority: Literal["low", "medium", "high"] = "medium"
    evidence_time: str | None = Field(default=None, description="Timestamp copied from the transcript, e.g. '05:30'")
    evidence_start_ms: int | None = Field(default=None, ge=0)
    evidence_quote: str = Field(default="", max_length=500)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _time_to_ms(self):
        if self.evidence_start_ms is None:
            self.evidence_start_ms = parse_clock(self.evidence_time)
        return self


class MinutePoint(BaseModel):
    time: str | None = Field(default=None, description="Timestamp from the transcript, e.g. '05:30'")
    start_ms: int = Field(default=0, ge=0)
    point: str

    @model_validator(mode="after")
    def _time_to_ms(self):
        if not self.start_ms and (ms := parse_clock(self.time)) is not None:
            self.start_ms = ms
        return self


class ExtractionResult(BaseModel):
    overview: str = ""
    decisions: list[str] = []
    minutes: list[MinutePoint] = []
    tasks: list[ExtractedTask] = []


# ---- API ---------------------------------------------------------------------

class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    language: str = "id"
    local_user_name: str | None = Field(default=None, max_length=100)
    started_at: datetime | None = None


class ParticipantOut(_ORM):
    id: str
    label: str
    name: str | None
    is_local_user: bool


class ParticipantPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)


class SegmentOut(_ORM):
    id: int
    participant_id: str | None
    source: str
    start_ms: int
    end_ms: int
    text: str


class SummaryOut(_ORM):
    overview: str
    decisions: list[str]
    minutes: list[MinutePoint]


class TaskOut(_ORM):
    id: str
    meeting_id: str
    title: str
    description: str
    assignee_name: str | None
    assignee_participant_id: str | None
    deadline_text: str | None
    deadline: date | None
    deadline_approximate: bool
    estimate_minutes: int | None
    priority: str
    confidence: float
    evidence_start_ms: int | None
    evidence_quote: str
    status: str


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = None
    assignee_participant_id: str | None = None
    assignee_name: str | None = None
    deadline: date | None = None
    estimate_minutes: int | None = Field(default=None, ge=1)
    priority: Literal["low", "medium", "high"] | None = None
    status: Literal["suggested", "confirmed", "rejected"] | None = None


class MeetingSummaryOut(_ORM):
    id: str
    title: str
    status: str
    language: str
    started_at: datetime
    ended_at: datetime | None
    error: str | None


class MeetingDetail(MeetingSummaryOut):
    participants: list[ParticipantOut]
    segments: list[SegmentOut]
    summary: SummaryOut | None
    tasks: list[TaskOut]


class JobOut(_ORM):
    id: str
    meeting_id: str
    kind: str
    status: str
    stage: str | None
    progress: int
    error: str | None
