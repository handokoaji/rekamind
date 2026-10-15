"""Engine contracts. Every concrete backend (CUDA faster-whisper, Vulkan
whisper.cpp, OpenVINO, a remote GPU server, an LLM provider...) implements one
of these, so the pipeline never knows which hardware it is running on."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..schemas import ExtractionResult


@dataclass(frozen=True)
class AsrSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SpeakerTurn:
    start_ms: int
    end_ms: int
    label: str


class Transcriber(Protocol):
    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]: ...


class Diarizer(Protocol):
    def diarize(self, wav: Path, num_speakers: int | None = None) -> list[SpeakerTurn]: ...


@dataclass
class ExtractionInput:
    title: str
    started_at: datetime
    language: str
    participants: list[str]
    transcript: str  # "[mm:ss] Name: text" lines


class Extractor(Protocol):
    def extract(self, inp: ExtractionInput) -> ExtractionResult: ...


@dataclass
class Engines:
    transcriber: Transcriber
    diarizer: Diarizer
    extractor: Extractor
    # Human-readable, shown by /api/capabilities so the UI can say what will run where.
    description: dict[str, str] = field(default_factory=dict)
    # Frees GPU/RAM held by loaded models. The worker calls it when the queue drains, so a
    # laptop does not keep a multi-GB model resident while the user is just browsing.
    release: Callable[[], None] | None = None
