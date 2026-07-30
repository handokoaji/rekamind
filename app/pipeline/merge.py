from dataclasses import dataclass

from app.asr.base import TranscriptSegmentResult
from app.diarization.diarizer import SpeakerSegment


@dataclass
class MergedSegment:
    source: str
    speaker_label: str
    start_ms: int
    end_ms: int
    text: str


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _best_label(segment: TranscriptSegmentResult, speaker_labels: list[SpeakerSegment]) -> str:
    best_label = "Speaker ?"
    best_overlap = 0
    for candidate in speaker_labels:
        overlap = _overlap_ms(segment.start_ms, segment.end_ms, candidate.start_ms, candidate.end_ms)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = candidate.label
    return best_label


def merge_segments(
    mic_segments: list[TranscriptSegmentResult],
    speaker_segments: list[TranscriptSegmentResult],
    speaker_labels: list[SpeakerSegment],
) -> list[MergedSegment]:
    merged = [
        MergedSegment(source="mic", speaker_label="Anda", start_ms=s.start_ms, end_ms=s.end_ms, text=s.text)
        for s in mic_segments
    ]
    merged += [
        MergedSegment(
            source="speaker", speaker_label=_best_label(s, speaker_labels),
            start_ms=s.start_ms, end_ms=s.end_ms, text=s.text,
        )
        for s in speaker_segments
    ]
    merged.sort(key=lambda seg: seg.start_ms)
    return merged
