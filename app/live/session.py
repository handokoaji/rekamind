import asyncio
import logging
import queue
import threading
from pathlib import Path
from typing import Callable

from app.live.diarize_loop import LiveDiarizeLoop
from app.live.pipeline import LiveSegment, StreamLivePipeline
from app.live.vad import SpeechSegmenter
from app.storage import repository as repo

logger = logging.getLogger(__name__)


class LiveSession:
    def __init__(
        self,
        mic_transcriber,
        speaker_transcriber,
        diarizer,
        segmenter_factory: Callable[[], SpeechSegmenter],
        mic_wav_path: Path,
        speaker_wav_path: Path,
        scratch_dir: Path,
        mic_queue: "queue.Queue",
        speaker_queue: "queue.Queue",
        diarize_interval_seconds: float,
        on_update: Callable[[dict], None],
        speaker_samplerate: int = 16000,
        speaker_channels: int = 1,
        meeting_id: int | None = None,
        session_factory=None,
    ):
        self._mic_queue = mic_queue
        self._speaker_queue = speaker_queue
        self._on_update = on_update
        # Public and mutable: the controller only learns the meeting id AFTER the
        # live session is constructed (the recorder factory needs the queues
        # first, and the meeting row is only written once recording started).
        # Drafts are simply skipped until it is set.
        self.meeting_id = meeting_id
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._mic_segments: list[LiveSegment] = []
        self._speaker_segments: list[LiveSegment] = []
        scratch_dir.mkdir(parents=True, exist_ok=True)

        def make_on_segment(target_list):
            def _on_segment(segment: LiveSegment):
                with self._lock:
                    target_list.append(segment)
                self._on_update({"type": "text", "segment": segment})
                self._save_draft(segment)
            return _on_segment

        self._mic_pipeline = StreamLivePipeline(
            source="mic", segmenter=segmenter_factory(), transcriber=mic_transcriber,
            scratch_dir=scratch_dir, samplerate=16000, on_segment=make_on_segment(self._mic_segments),
        )
        self._speaker_pipeline = StreamLivePipeline(
            source="speaker", segmenter=segmenter_factory(), transcriber=speaker_transcriber,
            scratch_dir=scratch_dir, samplerate=16000, on_segment=make_on_segment(self._speaker_segments),
            source_samplerate=speaker_samplerate, source_channels=speaker_channels,
        )

        def _on_relabeled(merged):
            self._on_update({"type": "relabel", "segments": merged})
            self._save_relabeled_drafts(merged)

        self._diarize_loop = LiveDiarizeLoop(
            diarizer=diarizer, speaker_wav_path=speaker_wav_path,
            interval_seconds=diarize_interval_seconds, get_segments=self.get_segments,
            on_relabeled=_on_relabeled,
        )
        self._threads: list[threading.Thread] = []

    # -- draft persistence (spec §4: live text survives a crash before "Stop") --

    def _save_draft(self, segment: LiveSegment) -> None:
        if self._session_factory is None or self.meeting_id is None:
            return

        async def _write():
            async with self._session_factory() as session:
                await repo.save_transcript_segments(session, [{
                    "meeting_id": self.meeting_id,
                    "speaker_id": None,  # unlabeled until the diarize loop relabels
                    "source": segment.source,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": segment.text,
                    "is_final": False,
                }])
                await session.commit()

        try:
            asyncio.run(_write())
        except Exception as exc:
            # A DB hiccup must never kill the consumer thread (spec §5).
            logger.warning("failed to save live draft segment: %s", exc)

    def _save_relabeled_drafts(self, merged) -> None:
        if self._session_factory is None or self.meeting_id is None:
            return

        async def _write():
            async with self._session_factory() as session:
                await repo.clear_draft_segments(session, self.meeting_id)
                # Same speaker-id resolution as pipeline/finalize.py.
                label_to_speaker_id: dict[str, int | None] = {"Anda": None}
                rows = []
                for seg in merged:
                    speaker_id = None
                    if seg.speaker_label != "Anda":
                        if seg.speaker_label not in label_to_speaker_id:
                            speaker = await repo.get_or_create_speaker(
                                session, self.meeting_id, seg.speaker_label
                            )
                            label_to_speaker_id[seg.speaker_label] = speaker.id
                        speaker_id = label_to_speaker_id[seg.speaker_label]
                    rows.append({
                        "meeting_id": self.meeting_id,
                        "speaker_id": speaker_id,
                        "source": seg.source,
                        "start_ms": seg.start_ms,
                        "end_ms": seg.end_ms,
                        "text": seg.text,
                        "is_final": False,
                    })
                await repo.save_transcript_segments(session, rows)
                await session.commit()

        try:
            asyncio.run(_write())
        except Exception as exc:
            logger.warning("failed to persist relabeled live drafts: %s", exc)

    def get_segments(self) -> tuple[list[LiveSegment], list[LiveSegment]]:
        with self._lock:
            return list(self._mic_segments), list(self._speaker_segments)

    def start(self) -> None:
        self._stop_event.clear()

        def _consume(source_queue, pipeline, source_name):
            while not self._stop_event.is_set():
                try:
                    chunk, absolute_start_sample = source_queue.get(timeout=0.5)
                except queue.Empty:
                    continue  # nothing yet; just re-check the stop flag
                try:
                    pipeline.feed_chunk(chunk, absolute_start_sample)
                except Exception as exc:
                    # spec §5: a live-pipeline error must never crash the app or
                    # silently kill this consumer thread - log and keep consuming
                    # (WAV capture, on a separate path entirely, is unaffected).
                    logger.warning("live %s pipeline error, skipping this chunk: %s", source_name, exc)

        mic_thread = threading.Thread(target=_consume, args=(self._mic_queue, self._mic_pipeline, "mic"), daemon=True)
        speaker_thread = threading.Thread(target=_consume, args=(self._speaker_queue, self._speaker_pipeline, "speaker"), daemon=True)
        mic_thread.start()
        speaker_thread.start()
        self._threads = [mic_thread, speaker_thread]
        self._diarize_loop.start()

    def stop(self) -> None:
        # An Event, not a sentinel in the queue: the production queues are bounded
        # (maxsize=200) so put() could block, and even once it landed the sentinel
        # would sit behind a whole backlog the consumer must transcribe first.
        # Setting the flag lets the consumers abandon their backlog and exit now.
        self._diarize_loop.stop()
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=5)
