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


def test_stop_shuts_down_the_diarizer_worker_if_it_has_one():
    """ProcessIsolatedDiarizer holds a full pyannote model copy in a worker
    process -- it must not stay resident for the rest of the app run once a
    meeting's recording stops."""
    shutdown_calls = []

    class FakeProcessIsolatedDiarizer(FakeDiarizer):
        def shutdown(self):
            shutdown_calls.append(1)

    loop = LiveDiarizeLoop(
        diarizer=FakeProcessIsolatedDiarizer([]),
        speaker_wav_path="speaker.wav",
        interval_seconds=8.0,
        get_segments=lambda: ([], []),
        on_relabeled=lambda merged: None,
    )

    loop.stop()

    assert shutdown_calls == [1]


def test_stop_does_not_crash_when_the_diarizer_has_no_shutdown():
    """The plain batch Diarizer (and most test doubles) has no shutdown() --
    stop() must be a no-op for those, not an AttributeError."""
    loop = LiveDiarizeLoop(
        diarizer=FakeDiarizer([]),
        speaker_wav_path="speaker.wav",
        interval_seconds=8.0,
        get_segments=lambda: ([], []),
        on_relabeled=lambda merged: None,
    )

    loop.stop()  # must not raise


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
