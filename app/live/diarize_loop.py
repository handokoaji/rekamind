import logging
import threading
from pathlib import Path
from typing import Callable

from app.asr.base import TranscriptSegmentResult
from app.pipeline.merge import MergedSegment, merge_segments

logger = logging.getLogger(__name__)


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
        # The diarizer may only cover a recent window of the recording (see
        # Diarizer.diarize), so a speaker segment before that window gets no
        # overlap and merge_segments falls back to "Speaker ?" -- remember the
        # last real label per segment so old segments don't visibly un-label
        # themselves on every tick.
        self._last_labels: dict[tuple[str, int], str] = {}

    def tick(self) -> None:
        mic_segments, speaker_segments = self._get_segments()
        size = Path(self._speaker_wav_path).stat().st_size if Path(self._speaker_wav_path).exists() else -1
        logger.info("diarize tick: wav=%s size=%d bytes", self._speaker_wav_path, size)
        speaker_labels = self._diarizer.diarize(self._speaker_wav_path)
        merged = merge_segments(
            [TranscriptSegmentResult(s.start_ms, s.end_ms, s.text) for s in mic_segments],
            [TranscriptSegmentResult(s.start_ms, s.end_ms, s.text) for s in speaker_segments],
            speaker_labels,
        )
        for seg in merged:
            if seg.source != "speaker":
                continue
            key = (seg.source, seg.start_ms)
            if seg.speaker_label == "Speaker ?" and key in self._last_labels:
                seg.speaker_label = self._last_labels[key]
            else:
                self._last_labels[key] = seg.speaker_label
        self._on_relabeled(merged)

    def start(self) -> None:
        self._stop_event.clear()

        def _run():
            while not self._stop_event.wait(self._interval_seconds):
                try:
                    self.tick()
                except Exception as exc:
                    logger.warning("live diarize tick failed, will retry next interval: %s", exc)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        # ProcessIsolatedDiarizer (live path) holds a full pyannote model
        # copy in its worker process; without this it stays resident for the
        # rest of the app run even between meetings. shutdown() only tears
        # down the worker -- the diarizer object itself (cached in main.py's
        # live_session_factory closure) is untouched, so the next meeting's
        # first diarize() call just respawns a fresh worker lazily, same as
        # the existing crash/timeout recovery path already does. Duck-typed:
        # the plain (non-process-isolated) Diarizer used for the batch pass,
        # and test doubles, have no shutdown() to call.
        shutdown = getattr(self._diarizer, "shutdown", None)
        if shutdown is not None:
            shutdown()
