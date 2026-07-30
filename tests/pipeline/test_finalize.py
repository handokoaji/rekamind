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
