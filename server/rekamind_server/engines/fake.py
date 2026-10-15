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
    def diarize(self, wav: Path, num_speakers: int | None = None) -> list[SpeakerTurn]:
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
                ExtractedTask(title="Kirim laporan", assignee="Saya", deadline_text="Jumat depan", confidence=0.6,
                              evidence_start_ms=20000, evidence_quote="Saya kirim laporan Jumat depan."),
            ],
        )


def fake_engines() -> Engines:
    return Engines(FakeTranscriber(), FakeDiarizer(), FakeExtractor(),
                   {"transcriber": "fake", "diarizer": "fake", "extractor": "fake"})


# --- Isi rapat contoh yang realistis, hanya untuk screenshot dokumentasi (REKAMIND_ENGINES=demo) ---
_MIC = [(0, 6000, "Selamat pagi semuanya, kita mulai rapat peluncuran fitur laporan bulanan."),
        (31000, 38000, "Saya bisa selesaikan dashboardnya sebelum hari Kamis, tinggal pengujian akhir."),
        (62000, 68000, "Baik, kalau begitu saya hubungi vendor untuk perpanjang lisensinya hari ini."),
        (95000, 101000, "Oke, kita sepakat peluncuran digeser ke minggu depan. Terima kasih semuanya.")]
_SPK = [(7000, 15000, "Terima kasih Pak Andi. Dari sisi desain, mockup halaman laporan sudah final."),
        (16000, 25000, "Rina, tolong kirim ringkasan perubahan ke tim QA paling lambat besok siang."),
        (39000, 47000, "Untuk data uji, Dewi akan menyiapkan dataset bulan September, sekitar tiga jam kerja."),
        (70000, 79000, "Anggaran vendor masih aman. Jadi peluncuran bisa dijadwalkan Senin depan.")]


class DemoTranscriber:
    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        return [AsrSegment(a, b, t) for a, b, t in (_MIC if wav.stem == "mic" else _SPK)]


class DemoDiarizer:
    def diarize(self, wav: Path, num_speakers: int | None = None) -> list[SpeakerTurn]:
        return [SpeakerTurn(7000, 25000, "SPEAKER_00"), SpeakerTurn(39000, 47000, "SPEAKER_01"),
                SpeakerTurn(70000, 79000, "SPEAKER_00")]


class DemoExtractor:
    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        return ExtractionResult(
            overview="Tim membahas kesiapan peluncuran fitur laporan bulanan. Desain sudah final, dashboard "
                     "tinggal pengujian akhir, dan peluncuran disepakati digeser ke minggu depan.",
            decisions=["Peluncuran digeser ke Senin minggu depan", "Lisensi vendor diperpanjang dalam anggaran yang ada"],
            minutes=[MinutePoint(start_ms=0, point="Pembukaan dan status peluncuran"),
                     MinutePoint(start_ms=7000, point="Desain halaman laporan sudah final"),
                     MinutePoint(start_ms=31000, point="Dashboard selesai sebelum Kamis, data uji disiapkan"),
                     MinutePoint(start_ms=62000, point="Perpanjangan lisensi vendor dan keputusan jadwal")],
            tasks=[
                ExtractedTask(title="Selesaikan dashboard laporan", assignee="Andi", deadline_text="sebelum hari Kamis",
                              estimate_minutes=480, priority="high", evidence_start_ms=31000, confidence=0.93,
                              evidence_quote="Saya bisa selesaikan dashboardnya sebelum hari Kamis, tinggal pengujian akhir."),
                ExtractedTask(title="Kirim ringkasan perubahan ke tim QA", assignee="Rina", deadline_text="besok siang",
                              estimate_minutes=30, priority="medium", evidence_start_ms=16000, confidence=0.88,
                              evidence_quote="Rina, tolong kirim ringkasan perubahan ke tim QA paling lambat besok siang."),
                ExtractedTask(title="Siapkan dataset uji bulan September", assignee="Dewi", deadline_text=None,
                              estimate_minutes=180, priority="medium", evidence_start_ms=39000, confidence=0.82,
                              evidence_quote="Dewi akan menyiapkan dataset bulan September, sekitar tiga jam kerja."),
                ExtractedTask(title="Hubungi vendor untuk perpanjang lisensi", assignee="Andi", deadline_text="hari ini",
                              estimate_minutes=45, priority="high", evidence_start_ms=62000, confidence=0.9,
                              evidence_quote="saya hubungi vendor untuk perpanjang lisensinya hari ini."),
                ExtractedTask(title="Umumkan jadwal peluncuran baru", assignee=None, deadline_text="Senin depan",
                              priority="low", evidence_start_ms=95000, confidence=0.55,
                              evidence_quote="kita sepakat peluncuran digeser ke minggu depan."),
            ],
        )


def demo_engines() -> Engines:
    return Engines(DemoTranscriber(), DemoDiarizer(), DemoExtractor(),
                   {"transcriber": "demo", "diarizer": "demo", "extractor": "demo"})
