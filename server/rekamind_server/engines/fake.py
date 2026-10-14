"""Deterministic engines for tests and for running the UI without any model installed."""

from pathlib import Path

from ..schemas import ExtractedTask, ExtractionResult, MinutePoint
from .base import AsrSegment, Engines, ExtractionInput, SpeakerTurn


class FakeTranscriber:
    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        if wav.stem == "mic":
            return [AsrSegment(0, 4000, "Baik, kita mulai rapatnya."),
                    AsrSegment(20000, 24000, "Saya kirim laporan Jumat depan.")]
        return [AsrSegment(5000, 9000, "Budi tolong siapkan draft kontrak besok."),
                AsrSegment(10000, 14000, "Siap, saya kerjakan, sekitar dua jam.")]


class FakeDiarizer:
    def diarize(self, wav: Path) -> list[SpeakerTurn]:
        return [SpeakerTurn(4500, 9500, "SPEAKER_00"), SpeakerTurn(9800, 14500, "SPEAKER_01")]


class FakeExtractor:
    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        return ExtractionResult(
            overview=f"Ringkasan {inp.title}",
            decisions=["Draft kontrak disiapkan sebelum rapat berikutnya"],
            minutes=[MinutePoint(start_ms=0, point="Pembukaan")],
            tasks=[
                ExtractedTask(title="Siapkan draft kontrak", assignee="Budi", deadline_text="besok",
                              estimate_minutes=120, priority="high", evidence_start_ms=5000,
                              evidence_quote="Budi tolong siapkan draft kontrak besok.", confidence=0.9),
                ExtractedTask(title="Siapkan draft kontrak", assignee="budi", deadline_text="besok"),  # duplicate
                ExtractedTask(title="Kirim laporan", assignee="Saya", deadline_text="Jumat depan", confidence=0.6),
            ],
        )


def fake_engines() -> Engines:
    return Engines(FakeTranscriber(), FakeDiarizer(), FakeExtractor(),
                   {"transcriber": "fake", "diarizer": "fake", "extractor": "fake"})
