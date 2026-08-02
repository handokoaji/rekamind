from dataclasses import dataclass


@dataclass
class SpeakerSegment:
    start_ms: int
    end_ms: int
    label: str
