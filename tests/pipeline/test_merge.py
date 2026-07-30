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
