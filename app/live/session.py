import queue
import threading
from pathlib import Path
from typing import Callable

from app.live.diarize_loop import LiveDiarizeLoop
from app.live.pipeline import LiveSegment, StreamLivePipeline
from app.live.vad import SpeechSegmenter


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
    ):
        self._mic_queue = mic_queue
        self._speaker_queue = speaker_queue
        self._on_update = on_update
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
            return _on_segment

        self._mic_pipeline = StreamLivePipeline(
            source="mic", segmenter=segmenter_factory(), transcriber=mic_transcriber,
            scratch_dir=scratch_dir, samplerate=16000, on_segment=make_on_segment(self._mic_segments),
        )
        # Only the speaker source needs conversion: mic capture is already forced to
        # 16kHz mono by AudioDeviceConfig, but WASAPI loopback records native format.
        self._speaker_pipeline = StreamLivePipeline(
            source="speaker", segmenter=segmenter_factory(), transcriber=speaker_transcriber,
            scratch_dir=scratch_dir, samplerate=16000, on_segment=make_on_segment(self._speaker_segments),
            source_samplerate=speaker_samplerate, source_channels=speaker_channels,
        )
        self._diarize_loop = LiveDiarizeLoop(
            diarizer=diarizer, speaker_wav_path=speaker_wav_path,
            interval_seconds=diarize_interval_seconds, get_segments=self.get_segments,
            on_relabeled=lambda merged: self._on_update({"type": "relabel", "segments": merged}),
        )
        self._threads: list[threading.Thread] = []

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
                    print(f"WARNING: live {source_name} pipeline error, skipping this chunk: {exc}")

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
