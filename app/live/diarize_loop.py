import threading
from pathlib import Path
from typing import Callable

from app.asr.base import TranscriptSegmentResult
from app.pipeline.merge import MergedSegment, merge_segments


class LiveDiarizeLoop:
    def __init__(
        self,
        diarizer,
        speaker_wav_path: Path,
        interval_seconds: float,
        get_segments: Callable[[], tuple[list, list]],
        on_relabeled: Callable[[list[MergedSegment]], None],
    ):
        self._diarizer = diarizer
        self._speaker_wav_path = speaker_wav_path
        self._interval_seconds = interval_seconds
        self._get_segments = get_segments
        self._on_relabeled = on_relabeled
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> None:
        mic_segments, speaker_segments = self._get_segments()
        speaker_labels = self._diarizer.diarize(self._speaker_wav_path)
        merged = merge_segments(
            [TranscriptSegmentResult(s.start_ms, s.end_ms, s.text) for s in mic_segments],
            [TranscriptSegmentResult(s.start_ms, s.end_ms, s.text) for s in speaker_segments],
            speaker_labels,
        )
        self._on_relabeled(merged)

    def start(self) -> None:
        self._stop_event.clear()

        def _run():
            while not self._stop_event.wait(self._interval_seconds):
                try:
                    self.tick()
                except Exception as exc:
                    print(f"WARNING: live diarize tick failed, will retry next interval: {exc}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
