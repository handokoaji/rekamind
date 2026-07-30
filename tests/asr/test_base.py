from pathlib import Path

from app.asr.base import TranscriberBackend, TranscriptSegmentResult


class FakeBackend:
    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        return [TranscriptSegmentResult(start_ms=0, end_ms=500, text="halo")]


def test_fake_backend_satisfies_protocol():
    backend: TranscriberBackend = FakeBackend()
    result = backend.transcribe(Path("dummy.wav"))
    assert result == [TranscriptSegmentResult(start_ms=0, end_ms=500, text="halo")]
