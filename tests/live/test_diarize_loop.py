from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment
from app.live.diarize_loop import LiveDiarizeLoop
from app.live.pipeline import LiveSegment
from app.pipeline.merge import MergedSegment


class FakeDiarizer:
    def __init__(self, labels):
        self._labels = labels

    def diarize(self, wav_path):
        return self._labels


def test_tick_merges_current_segments_with_fresh_diarization():
    mic_segments = [LiveSegment(source="mic", start_ms=0, end_ms=400, text="Selamat pagi")]
    speaker_segments = [LiveSegment(source="speaker", start_ms=500, end_ms=1200, text="Mari mulai")]

    diarizer = FakeDiarizer([SpeakerSegment(start_ms=450, end_ms=1300, label="Speaker 1")])
    received = []

    loop = LiveDiarizeLoop(
        diarizer=diarizer,
        speaker_wav_path="speaker.wav",
        interval_seconds=8.0,
        get_segments=lambda: (mic_segments, speaker_segments),
        on_relabeled=received.append,
    )

    loop.tick()

    assert len(received) == 1
    merged = received[0]
    assert merged == [
        MergedSegment(source="mic", speaker_label="Anda", start_ms=0, end_ms=400, text="Selamat pagi"),
        MergedSegment(source="speaker", speaker_label="Speaker 1", start_ms=500, end_ms=1200, text="Mari mulai"),
    ]


def test_tick_with_no_segments_yet_calls_on_relabeled_with_empty_list():
    diarizer = FakeDiarizer([])
    received = []

    loop = LiveDiarizeLoop(
        diarizer=diarizer,
        speaker_wav_path="speaker.wav",
        interval_seconds=8.0,
        get_segments=lambda: ([], []),
        on_relabeled=received.append,
    )

    loop.tick()

    assert received == [[]]
