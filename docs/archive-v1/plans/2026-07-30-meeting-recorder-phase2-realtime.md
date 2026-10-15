# Meeting Recorder — Fase 2 (Real-time Streaming) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a meeting is recording, show transcript text live in the Tkinter window (small ASR model, near-real-time) with speaker labels catching up every ~8 seconds — without disturbing the existing WAV capture or the Fase-1 batch pipeline that runs after Stop.

**Architecture:** Audio capture (unchanged) pushes raw PCM chunks onto two bounded queues (mic, speaker). Two background consumer threads drain those queues through a VAD segmenter and the small ASR model, appending unlabeled `LiveSegment`s. A third timer thread re-diarizes the full speaker WAV every ~8s and re-labels all segments accumulated so far via the existing `merge_segments`. Both the live-text and the re-label events are pushed onto one thread-safe queue that the Tkinter window drains via `root.after` polling — the same pattern Fase 1 already uses for status updates.

**Tech Stack:** silero-vad (VADIterator) for speech segmentation, the existing `TranscriberBackend`/`Diarizer`/`merge_segments` from Fase 1 reused unchanged (just a smaller model size for the live pass), Python `threading`/`queue` stdlib.

## Global Constraints

- Live preview never blocks or crashes the recording itself: any live-pipeline error is caught, logged, and preview simply stops updating — WAV capture continues (spec §5).
- Live text is a draft: stored as `TranscriptSegment` rows with `is_final=False`, and `finalize_meeting` must delete all drafts for the meeting before saving the final (`is_final=True`) segments (spec §4 step 5).
- Diarization during live preview re-processes the ENTIRE `speaker.wav` recorded so far every ~8 seconds (not a sliding window) — speaker numbering must stay consistent for the whole meeting (spec §2).
- PyAudio's audio callback thread must stay fast: it may only push raw bytes onto a queue, never run VAD/ASR/diarization directly (real-time audio safety).
- No change to Fase 1's batch pipeline behavior or its existing files' public interfaces (`finalize_meeting`, `merge_segments`, `TranscriberBackend`, `Diarizer`) beyond what's explicitly listed below.
- Bahasa Indonesia UI/labels, Windows-only, matches existing project conventions (`app/` module layout, pytest + TDD, `.venv/Scripts/python.exe`).

---

### Task 1: WavFileWriter — flush after every write

**Files:**
- Modify: `app/audio/wav_writer.py`
- Test: `tests/audio/test_wav_writer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `WavFileWriter.write_frames` now flushes to disk after every call, so a second, independent read of the same (still-open) file reflects data written so far. Needed because Task 7's diarize loop reads `speaker.wav` while Fase 1's capture is still actively writing it.

- [ ] **Step 1: Write the failing test**

```python
# tests/audio/test_wav_writer.py (append)
def test_write_frames_flushes_so_concurrent_reader_sees_data(tmp_path):
    import wave

    path = tmp_path / "live.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    writer = WavFileWriter(path, samplerate=16000, channels=1)
    writer.write_frames(frame)

    # Second, independent read handle on the SAME still-open file.
    with wave.open(str(path), "rb") as reader:
        assert reader.getnframes() == 160

    writer.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/audio/test_wav_writer.py::test_write_frames_flushes_so_concurrent_reader_sees_data -v`
Expected: FAIL — `wave.Error` or the reader sees 0 frames (header not updated), since nothing flushes yet.

- [ ] **Step 3: Write minimal implementation**

```python
# app/audio/wav_writer.py
import wave
from pathlib import Path


class WavFileWriter:
    def __init__(self, path: Path, samplerate: int, channels: int, sample_width: int = 2):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wf = wave.open(str(path), "wb")
        try:
            self._wf.setnchannels(channels)
            self._wf.setsampwidth(sample_width)
            self._wf.setframerate(samplerate)
        except Exception:
            self._wf.close()
            raise

    def write_frames(self, frames: bytes) -> None:
        self._wf.writeframes(frames)
        # wave.Wave_write buffers via its underlying file object and only
        # patches the RIFF header's size fields on close(); a concurrent
        # reader needs both the audio bytes AND the header flushed now.
        self._wf._file.flush()
        self._wf._patchheader()

    def close(self) -> None:
        self._wf.close()

    def __enter__(self) -> "WavFileWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/audio/test_wav_writer.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Commit**

```bash
git add app/audio/wav_writer.py tests/audio/test_wav_writer.py
git commit -m "feat: flush WAV header+data after every write for concurrent readers"
```

---

### Task 2: Audio capture — tap frames to live queues

**Files:**
- Modify: `app/audio/capture.py`
- Test: `tests/audio/test_capture.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `frame_callback(frames: bytes, writer: WavFileWriter, live_queue: "queue.Queue | None" = None) -> None` — now also offers a copy of `frames` to `live_queue` (non-blocking, drops on full rather than stalling the audio thread). `MicSpeakerRecorder.__init__` gains optional `mic_queue: queue.Queue | None = None, speaker_queue: queue.Queue | None = None` params; when given, they receive raw PCM chunks as they arrive from the corresponding stream.

- [ ] **Step 1: Write the failing test**

```python
# tests/audio/test_capture.py (append)
import queue

from app.audio.capture import frame_callback


def test_frame_callback_pushes_to_live_queue_without_blocking(tmp_path):
    from app.audio.wav_writer import WavFileWriter

    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    live_queue = queue.Queue(maxsize=2)

    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        frame_callback(frame, writer, live_queue=live_queue)

    assert live_queue.get_nowait() == frame


def test_frame_callback_drops_frame_when_queue_full_instead_of_blocking(tmp_path):
    from app.audio.wav_writer import WavFileWriter

    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    live_queue = queue.Queue(maxsize=1)
    live_queue.put_nowait(b"already-full")

    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        # Must not raise or block even though the queue has no room.
        frame_callback(frame, writer, live_queue=live_queue)

    assert live_queue.get_nowait() == b"already-full"


def test_frame_callback_without_live_queue_still_works(tmp_path):
    from app.audio.wav_writer import WavFileWriter

    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        frame_callback(frame, writer)  # no live_queue passed at all
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/audio/test_capture.py -v -k live_queue`
Expected: FAIL with `TypeError: frame_callback() got an unexpected keyword argument 'live_queue'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/audio/capture.py
import queue
from dataclasses import dataclass
from pathlib import Path

from app.audio.wav_writer import WavFileWriter


@dataclass
class AudioDeviceConfig:
    samplerate: int = 16000
    channels: int = 1


def frame_callback(frames: bytes, writer: WavFileWriter, live_queue: "queue.Queue | None" = None) -> None:
    writer.write_frames(frames)
    if live_queue is not None:
        try:
            live_queue.put_nowait(frames)
        except queue.Full:
            pass  # live preview is best-effort; the WAV write above already happened


class MicSpeakerRecorder:
    """Captures mic input and WASAPI speaker loopback in parallel to two WAV files.

    Real device I/O uses pyaudiowpatch (Windows-only WASAPI loopback support).
    Import is deferred into start() so this module can be imported and the
    frame_callback logic tested on any platform without pyaudiowpatch installed.
    """

    def __init__(
        self,
        mic_path: Path,
        speaker_path: Path,
        config: AudioDeviceConfig | None = None,
        mic_queue: "queue.Queue | None" = None,
        speaker_queue: "queue.Queue | None" = None,
    ):
        self._mic_path = mic_path
        self._speaker_path = speaker_path
        self._config = config or AudioDeviceConfig()
        self._mic_queue = mic_queue
        self._speaker_queue = speaker_queue
        self._pyaudio = None
        self._mic_stream = None
        self._speaker_stream = None
        self._mic_writer: WavFileWriter | None = None
        self._speaker_writer: WavFileWriter | None = None

    def start(self) -> None:
        if self._pyaudio is not None:
            raise RuntimeError("recorder is already started")

        import pyaudiowpatch as pyaudio

        self._pyaudio = pyaudio.PyAudio()
        self._mic_writer = WavFileWriter(self._mic_path, self._config.samplerate, self._config.channels)

        default_speakers = self._pyaudio.get_default_wasapi_loopback()
        speaker_samplerate = int(default_speakers["defaultSampleRate"])
        speaker_channels = default_speakers["maxInputChannels"]
        self._speaker_writer = WavFileWriter(self._speaker_path, speaker_samplerate, speaker_channels)

        def mic_stream_callback(in_data, frame_count, time_info, status):
            frame_callback(in_data, self._mic_writer, self._mic_queue)
            return (None, pyaudio.paContinue)

        def speaker_stream_callback(in_data, frame_count, time_info, status):
            frame_callback(in_data, self._speaker_writer, self._speaker_queue)
            return (None, pyaudio.paContinue)

        self._mic_stream = self._pyaudio.open(
            format=pyaudio.paInt16, channels=self._config.channels,
            rate=self._config.samplerate, input=True,
            stream_callback=mic_stream_callback,
        )
        self._speaker_stream = self._pyaudio.open(
            format=pyaudio.paInt16, channels=speaker_channels,
            rate=speaker_samplerate, input=True,
            input_device_index=default_speakers["index"],
            stream_callback=speaker_stream_callback,
        )
        self._mic_stream.start_stream()
        self._speaker_stream.start_stream()

    def stop(self) -> tuple[Path, Path]:
        if self._pyaudio is None:
            raise RuntimeError("recorder was never started")

        for stream in (self._mic_stream, self._speaker_stream):
            if stream is not None:
                stream.stop_stream()
                stream.close()
        if self._pyaudio is not None:
            self._pyaudio.terminate()
        if self._mic_writer is not None:
            self._mic_writer.close()
        if self._speaker_writer is not None:
            self._speaker_writer.close()
        return self._mic_path, self._speaker_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/audio/test_capture.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/audio/capture.py tests/audio/test_capture.py
git commit -m "feat: tap raw audio frames to optional live-preview queues"
```

---

### Task 3: VAD speech segmenter

**Files:**
- Create: `app/live/__init__.py`
- Create: `app/live/vad.py`
- Test: `tests/live/test_vad.py`
- Create: `tests/live/__init__.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `app.live.vad.SpeechSegment` (dataclass: `start_sample: int, audio: bytes`)
  - `app.live.vad.SpeechSegmenter(vad_iterator, samplerate: int = 16000)` with `process_chunk(self, chunk: bytes) -> list[SpeechSegment]` — buffers arbitrary-length incoming byte chunks into fixed 512-sample (1024-byte, 16-bit mono) windows, feeds each window to `vad_iterator(tensor, return_seconds=False)`, and returns a `SpeechSegment` for each speech span that just closed (a `{"end": ...}` event). `vad_iterator` is any callable matching silero-vad's `VADIterator.__call__` signature — injected for testability.
  - `app.live.vad.load_silero_vad_iterator(samplerate: int = 16000)` — real factory, deferred imports, loads the actual `silero-vad` pip package's `VADIterator`.

- [ ] **Step 1: Write the failing test**

```python
# tests/live/test_vad.py
from app.live.vad import SpeechSegment, SpeechSegmenter

WINDOW_SAMPLES = 512
WINDOW_BYTES = WINDOW_SAMPLES * 2  # int16 mono


def _window(value: int = 1) -> bytes:
    return value.to_bytes(2, "little", signed=True) * WINDOW_SAMPLES


def test_segmenter_emits_segment_spanning_start_to_end_windows():
    calls = []

    def fake_vad_iterator(tensor, return_seconds=False):
        calls.append(tensor)
        if len(calls) == 1:
            return {"start": 0}
        if len(calls) == 3:
            return {"end": 1536}
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)

    results = []
    for _ in range(3):
        results.extend(segmenter.process_chunk(_window()))

    assert len(results) == 1
    assert isinstance(results[0], SpeechSegment)
    assert results[0].start_sample == 0
    assert len(results[0].audio) == WINDOW_BYTES * 3


def test_segmenter_buffers_partial_chunks_across_calls():
    """Chunks smaller than one VAD window must accumulate, not be dropped."""
    calls = []

    def fake_vad_iterator(tensor, return_seconds=False):
        calls.append(tensor)
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)

    half = _window()[: WINDOW_BYTES // 2]
    assert segmenter.process_chunk(half) == []  # not enough for one window yet
    assert len(calls) == 0
    assert segmenter.process_chunk(half) == []  # now exactly one window's worth
    assert len(calls) == 1


def test_segmenter_returns_nothing_outside_speech():
    def fake_vad_iterator(tensor, return_seconds=False):
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)
    assert segmenter.process_chunk(_window()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/live/test_vad.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.live'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/live/__init__.py
```

```python
# app/live/vad.py
from dataclasses import dataclass

import numpy as np
import torch


@dataclass
class SpeechSegment:
    start_sample: int
    audio: bytes


def _bytes_to_tensor(window: bytes) -> "torch.Tensor":
    audio_int16 = np.frombuffer(window, dtype=np.int16)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0
    return torch.from_numpy(audio_float32)


class SpeechSegmenter:
    CHUNK_SAMPLES = 512  # silero-vad's required window size at 16kHz

    def __init__(self, vad_iterator, samplerate: int = 16000):
        self._vad_iterator = vad_iterator
        self._samplerate = samplerate
        self._pending = bytearray()
        self._speech_buffer = bytearray()
        self._in_speech = False
        self._samples_seen = 0
        self._speech_start_sample: int | None = None

    def process_chunk(self, chunk: bytes) -> list[SpeechSegment]:
        self._pending.extend(chunk)
        completed: list[SpeechSegment] = []
        window_bytes = self.CHUNK_SAMPLES * 2
        while len(self._pending) >= window_bytes:
            window = bytes(self._pending[:window_bytes])
            del self._pending[:window_bytes]
            completed.extend(self._process_window(window))
        return completed

    def _process_window(self, window: bytes) -> list[SpeechSegment]:
        window_start_sample = self._samples_seen
        self._samples_seen += self.CHUNK_SAMPLES

        tensor = _bytes_to_tensor(window)
        event = self._vad_iterator(tensor, return_seconds=False)

        completed: list[SpeechSegment] = []
        if event and "start" in event:
            self._in_speech = True
            self._speech_buffer = bytearray()
            self._speech_start_sample = window_start_sample
        if self._in_speech:
            self._speech_buffer.extend(window)
        if event and "end" in event:
            self._in_speech = False
            completed.append(SpeechSegment(
                start_sample=self._speech_start_sample,
                audio=bytes(self._speech_buffer),
            ))
            self._speech_buffer = bytearray()
            self._speech_start_sample = None
        return completed


def load_silero_vad_iterator(samplerate: int = 16000):
    from silero_vad import VADIterator, load_silero_vad

    model = load_silero_vad()
    return VADIterator(model, sampling_rate=samplerate)
```

```python
# tests/live/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/live/test_vad.py -v`
Expected: PASS

- [ ] **Step 5: Install silero-vad and commit**

```bash
./.venv/Scripts/python.exe -m pip install silero-vad
git add pyproject.toml app/live/__init__.py app/live/vad.py tests/live/__init__.py tests/live/test_vad.py
git commit -m "feat: add silero-vad speech segmenter for live preview"
```

(Add `"silero-vad"` to the `dependencies` list in `pyproject.toml` as part of this commit.)

- [ ] **Step 6 (manual, hardware-dependent): real smoke test**

```bash
./.venv/Scripts/python.exe -c "
from app.live.vad import load_silero_vad_iterator, SpeechSegmenter
iterator = load_silero_vad_iterator()
segmenter = SpeechSegmenter(iterator)
print('loaded OK')
"
```

If this fails with an import or signature error, check the actually-installed
`silero-vad` package's real API (`python -c "import silero_vad; help(silero_vad)"`)
and adjust `load_silero_vad_iterator` to match — Fase 1 hit exactly this kind
of drift more than once with `pyannote.audio` (`use_auth_token` renamed to
`token`, `Annotation` wrapped in a new `DiarizeOutput` class in a later
release) and the fix was always to trust the installed library's real
signature over what any doc/plan snapshot assumed.
Expected: prints `loaded OK` with no errors (downloads the silero-vad model on first run).

---

### Task 4: Live ASR pipeline (per audio source)

**Files:**
- Create: `app/live/pipeline.py`
- Test: `tests/live/test_pipeline.py`

**Interfaces:**
- Consumes: `app.live.vad.SpeechSegmenter`, `app.live.vad.SpeechSegment` (Task 3), `app.asr.base.TranscriberBackend` (Fase 1), `app.audio.wav_writer.WavFileWriter` (Fase 1/Task 1).
- Produces:
  - `app.live.pipeline.LiveSegment` (dataclass: `source: str, start_ms: int, end_ms: int, text: str`)
  - `app.live.pipeline.StreamLivePipeline(source: str, segmenter: SpeechSegmenter, transcriber: TranscriberBackend, scratch_dir: Path, samplerate: int, on_segment: Callable[[LiveSegment], None])` with `feed_chunk(self, chunk: bytes) -> None` — runs `chunk` through `segmenter`, and for every completed `SpeechSegment`, writes it to a scratch WAV file and transcribes it with `transcriber`, calling `on_segment` once per resulting `TranscriptSegmentResult` (absolute-timestamped by adding the segment's `start_sample`-derived offset).

- [ ] **Step 1: Write the failing test**

```python
# tests/live/test_pipeline.py
from pathlib import Path

from app.asr.base import TranscriptSegmentResult
from app.live.pipeline import LiveSegment, StreamLivePipeline
from app.live.vad import SpeechSegment


class FakeSegmenter:
    def __init__(self, segments_per_call):
        self._segments_per_call = list(segments_per_call)

    def process_chunk(self, chunk):
        return self._segments_per_call.pop(0) if self._segments_per_call else []


class FakeTranscriber:
    def __init__(self, results):
        self._results = results
        self.transcribed_paths = []

    def transcribe(self, wav_path, language="id"):
        self.transcribed_paths.append(wav_path)
        return self._results


def test_feed_chunk_transcribes_completed_segments_with_absolute_timestamps(tmp_path):
    silence_window = (0).to_bytes(2, "little", signed=True) * 512
    segmenter = FakeSegmenter([
        [SpeechSegment(start_sample=16000, audio=silence_window)],  # 1.0s in at 16kHz
    ])
    transcriber = FakeTranscriber([
        TranscriptSegmentResult(start_ms=0, end_ms=500, text="halo"),
    ])
    received: list[LiveSegment] = []

    pipeline = StreamLivePipeline(
        source="mic", segmenter=segmenter, transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=received.append,
    )

    pipeline.feed_chunk(silence_window)

    assert len(transcriber.transcribed_paths) == 1
    assert transcriber.transcribed_paths[0].exists()
    assert received == [LiveSegment(source="mic", start_ms=1000, end_ms=1500, text="halo")]


def test_feed_chunk_does_nothing_when_no_segment_completes(tmp_path):
    segmenter = FakeSegmenter([[]])
    transcriber = FakeTranscriber([])
    received = []

    pipeline = StreamLivePipeline(
        source="speaker", segmenter=segmenter, transcriber=transcriber,
        scratch_dir=tmp_path, samplerate=16000, on_segment=received.append,
    )
    pipeline.feed_chunk(b"\x00\x00" * 512)

    assert received == []
    assert transcriber.transcribed_paths == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/live/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.live.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/live/pipeline.py
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.asr.base import TranscriberBackend
from app.audio.wav_writer import WavFileWriter
from app.live.vad import SpeechSegmenter


@dataclass
class LiveSegment:
    source: str
    start_ms: int
    end_ms: int
    text: str


class StreamLivePipeline:
    def __init__(
        self,
        source: str,
        segmenter: SpeechSegmenter,
        transcriber: TranscriberBackend,
        scratch_dir: Path,
        samplerate: int,
        on_segment: Callable[[LiveSegment], None],
    ):
        self._source = source
        self._segmenter = segmenter
        self._transcriber = transcriber
        self._scratch_dir = scratch_dir
        self._samplerate = samplerate
        self._on_segment = on_segment
        self._segment_counter = 0

    def feed_chunk(self, chunk: bytes) -> None:
        for segment in self._segmenter.process_chunk(chunk):
            self._transcribe_segment(segment)

    def _transcribe_segment(self, segment) -> None:
        self._segment_counter += 1
        temp_path = self._scratch_dir / f"{self._source}_{self._segment_counter}.wav"
        with WavFileWriter(temp_path, self._samplerate, channels=1) as writer:
            writer.write_frames(segment.audio)

        offset_ms = int(segment.start_sample / self._samplerate * 1000)
        for result in self._transcriber.transcribe(temp_path, language="id"):
            self._on_segment(LiveSegment(
                source=self._source,
                start_ms=offset_ms + result.start_ms,
                end_ms=offset_ms + result.end_ms,
                text=result.text,
            ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/live/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/live/pipeline.py tests/live/test_pipeline.py
git commit -m "feat: add per-source live ASR pipeline (VAD -> small model -> LiveSegment)"
```

---

### Task 5: Repository — draft segments

**Files:**
- Modify: `app/storage/repository.py:58-68` (the existing `save_transcript_segments`)
- Test: `tests/storage/test_repository.py`

**Interfaces:**
- Consumes: `app.storage.models.TranscriptSegment` (unchanged).
- Produces:
  - `app.storage.repository.save_transcript_segments(session, segments: list[dict]) -> None` — each dict MAY now include an optional `"is_final"` key (defaults to `True` if absent, preserving every existing Fase 1 call site unchanged).
  - `app.storage.repository.clear_draft_segments(session, meeting_id: int) -> None` — deletes every `TranscriptSegment` row for `meeting_id` where `is_final == False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/storage/test_repository.py (append)
def test_save_transcript_segments_defaults_is_final_true():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Draft", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "final segment"},
            ])
            await session.commit()

        async with session_factory() as session:
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            result = await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )
            return result.scalars().all()

    segments = asyncio.run(scenario())
    assert len(segments) == 1
    assert segments[0].is_final is True


def test_save_transcript_segments_honors_is_final_false_and_clear_draft_segments_removes_only_drafts():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Draft", None)
            await session.commit()
            meeting_id = meeting.id

        async with session_factory() as session:
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 500, "text": "draft segment", "is_final": False},
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 500, "end_ms": 1000, "text": "final segment", "is_final": True},
            ])
            await session.commit()

        async with session_factory() as session:
            await repo.clear_draft_segments(session, meeting_id)
            await session.commit()

        async with session_factory() as session:
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            result = await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )
            return result.scalars().all()

    segments = asyncio.run(scenario())
    assert len(segments) == 1
    assert segments[0].text == "final segment"
    assert segments[0].is_final is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/storage/test_repository.py -v -k is_final`
Expected: FAIL — `clear_draft_segments` doesn't exist yet, and `is_final` isn't honored (both new segments would default to `True` today).

- [ ] **Step 3: Write minimal implementation**

```python
# app/storage/repository.py
# (add `delete` to the sqlalchemy import at the top)
from sqlalchemy import delete, select
```

```python
# app/storage/repository.py (replace save_transcript_segments, add clear_draft_segments)
async def save_transcript_segments(session: AsyncSession, segments: list[dict]) -> None:
    for seg in segments:
        session.add(TranscriptSegment(
            meeting_id=seg["meeting_id"],
            speaker_id=seg.get("speaker_id"),
            source=seg["source"],
            start_ms=seg["start_ms"],
            end_ms=seg["end_ms"],
            text=seg["text"],
            is_final=seg.get("is_final", True),
        ))
    await session.flush()


async def clear_draft_segments(session: AsyncSession, meeting_id: int) -> None:
    await session.execute(
        delete(TranscriptSegment).where(
            TranscriptSegment.meeting_id == meeting_id,
            TranscriptSegment.is_final.is_(False),
        )
    )
    await session.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/storage/test_repository.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add app/storage/repository.py tests/storage/test_repository.py
git commit -m "feat: support draft (is_final=False) transcript segments + clear_draft_segments"
```

---

### Task 6: finalize_meeting clears drafts before saving final segments

**Files:**
- Modify: `app/pipeline/finalize.py`
- Test: `tests/pipeline/test_finalize.py`

**Interfaces:**
- Consumes: `app.storage.repository.clear_draft_segments` (Task 5).
- Produces: `finalize_meeting` now calls `repo.clear_draft_segments(session, meeting_id)` immediately before `repo.save_transcript_segments(session, segment_rows)`, inside the same pre-existing try block (same transaction that already commits the transcript durably before the Groq/docx step).

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_finalize.py (append)
def test_finalize_meeting_clears_existing_drafts_before_saving_final_segments(tmp_path):
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat Uji", None)
            await session.commit()
            meeting_id = meeting.id

        # Simulate a leftover live-preview draft from before Stop was clicked.
        async with session_factory() as session:
            await repo.save_transcript_segments(session, [
                {"meeting_id": meeting_id, "speaker_id": None, "source": "mic",
                 "start_ms": 0, "end_ms": 400, "text": "draft yang belum sempat dihapus",
                 "is_final": False},
            ])
            await session.commit()

        mic_wav = tmp_path / "mic.wav"
        speaker_wav = tmp_path / "speaker.wav"
        mic_wav.touch()
        speaker_wav.touch()
        docx_path = tmp_path / "mom.docx"

        transcriber = RoutingFakeTranscriber({
            "mic.wav": [TranscriptSegmentResult(start_ms=0, end_ms=500, text="Selamat pagi")],
            "speaker.wav": [TranscriptSegmentResult(start_ms=600, end_ms=1500, text="Mari kita mulai")],
        })
        diarizer = FakeDiarizer([SpeakerSegment(start_ms=600, end_ms=1500, label="Speaker 1")])
        summarizer = FakeSummarizer()

        async with session_factory() as session:
            await finalize_meeting(
                session=session, meeting_id=meeting_id, meeting_title="Rapat Uji",
                meeting_date=datetime(2026, 7, 30, 9, 0), mic_wav=mic_wav, speaker_wav=speaker_wav,
                transcriber=transcriber, diarizer=diarizer, summarizer=summarizer,
                docx_output_path=docx_path,
            )
            await session.commit()

        async with session_factory() as session:
            from sqlalchemy import select
            from app.storage.models import TranscriptSegment
            result = await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            )
            return result.scalars().all()

    segments = asyncio.run(scenario())
    texts = {seg.text for seg in segments}
    assert "draft yang belum sempat dihapus" not in texts
    assert all(seg.is_final for seg in segments)
    assert "Selamat pagi" in texts
```

Note: this test reuses `RoutingFakeTranscriber`, `FakeDiarizer`, `FakeSummarizer`, `TranscriptSegmentResult`, `SpeakerSegment`, and the module-level imports already present in `tests/pipeline/test_finalize.py` from Fase 1 — no new fakes needed, just add this test function to the existing file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/pipeline/test_finalize.py -v -k clears_existing_drafts`
Expected: FAIL — the leftover draft segment is still present (`assert "draft yang belum sempat dihapus" not in texts` fails) since nothing clears it yet.

- [ ] **Step 3: Write minimal implementation**

In `app/pipeline/finalize.py`, inside `finalize_meeting`, immediately before the existing `await repo.save_transcript_segments(session, segment_rows)` line, add:

```python
        await repo.clear_draft_segments(session, meeting_id)
        await repo.save_transcript_segments(session, segment_rows)
        await session.commit()  # transcript is durable now, regardless of what happens next
```

(This replaces the two-line block that currently reads `await repo.save_transcript_segments(session, segment_rows)` followed by `await session.commit()` — just insert the `clear_draft_segments` call directly above `save_transcript_segments`, same try block, same transaction.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/pipeline/test_finalize.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/finalize.py tests/pipeline/test_finalize.py
git commit -m "feat: clear draft segments before saving final transcript"
```

---

### Task 7: Live diarize loop

**Files:**
- Create: `app/live/diarize_loop.py`
- Test: `tests/live/test_diarize_loop.py`

**Interfaces:**
- Consumes: `app.diarization.diarizer.Diarizer` (Fase 1), `app.pipeline.merge.merge_segments`, `app.pipeline.merge.MergedSegment` (Fase 1), `app.asr.base.TranscriptSegmentResult` (Fase 1), `app.live.pipeline.LiveSegment` (Task 4).
- Produces: `app.live.diarize_loop.LiveDiarizeLoop(diarizer, speaker_wav_path: Path, interval_seconds: float, get_segments: Callable[[], tuple[list[LiveSegment], list[LiveSegment]]], on_relabeled: Callable[[list[MergedSegment]], None])` with:
  - `tick(self) -> None` — calls `get_segments()` for the current `(mic_segments, speaker_segments)` snapshot, re-diarizes `speaker_wav_path` in full, merges, and calls `on_relabeled(merged)`. Pure/synchronous, fully unit-testable.
  - `start(self) -> None` / `stop(self) -> None` — run `tick()` on a background daemon thread every `interval_seconds`; an exception inside a single `tick()` is caught and logged so the loop keeps running for the next interval (spec §5). These two are thread-timing behavior, not unit-tested — verified by manual/hardware smoke test.

- [ ] **Step 1: Write the failing test**

```python
# tests/live/test_diarize_loop.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/live/test_diarize_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.live.diarize_loop'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/live/diarize_loop.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/live/test_diarize_loop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/live/diarize_loop.py tests/live/test_diarize_loop.py
git commit -m "feat: add live diarize loop (full re-diarization every ~8s)"
```

---

### Task 8: LiveSession — wires the live pipeline for one recording

**Files:**
- Create: `app/live/session.py`
- Test: `tests/live/test_session.py`

**Interfaces:**
- Consumes: `app.live.vad.SpeechSegmenter` (Task 3), `app.live.pipeline.StreamLivePipeline`, `app.live.pipeline.LiveSegment` (Task 4), `app.live.diarize_loop.LiveDiarizeLoop` (Task 7), `app.pipeline.merge.MergedSegment` (Fase 1).
- Produces: `app.live.session.LiveSession(mic_transcriber, speaker_transcriber, diarizer, vad_iterator_factory, mic_wav_path, speaker_wav_path, scratch_dir, mic_queue, speaker_queue, diarize_interval_seconds, on_update)` — a single object `RecorderController` (Task 9) holds one instance of per recording. `on_update: Callable[[dict], None]` receives events of shape `{"type": "text", "segment": LiveSegment}` (as soon as a live segment is transcribed) or `{"type": "relabel", "segments": list[MergedSegment]}` (every diarize-loop tick) — this is the SAME callback the UI queue (Task 10) will drain.
  - `start(self) -> None` — spawns two consumer threads (one per queue) each running a loop: pull a chunk (or a `None` sentinel to stop) from its queue, feed it to that source's `StreamLivePipeline`, forward every produced `LiveSegment` to `on_update({"type": "text", "segment": seg})` AND append it to an internal running list (mic list or speaker list) used by `get_segments()`. Also starts the `LiveDiarizeLoop`. Per spec §5, an exception from `pipeline.feed_chunk(chunk)` is caught and logged (`print(...)`), NOT re-raised — the consumer thread must keep pulling and processing subsequent chunks rather than dying silently on the first bad one (this closes the gap Task 4's review flagged: `StreamLivePipeline.feed_chunk` itself has no internal error handling, so this is the one place in the whole chain that must catch it).
  - `stop(self) -> None` — stops the diarize loop, pushes a `None` sentinel onto each queue to unblock and stop the consumer threads, joins them.
  - `get_segments(self) -> tuple[list[LiveSegment], list[LiveSegment]]` — thread-safe snapshot (`list(...)` copy) of `(mic_segments_so_far, speaker_segments_so_far)`, used both by `LiveDiarizeLoop` internally and available for inspection in tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/live/test_session.py
import queue
import time

from app.live.pipeline import LiveSegment
from app.live.session import LiveSession
from app.pipeline.merge import MergedSegment


class FakeSegmenter:
    """Treats every chunk as one completed speech segment (skips real VAD windowing)."""
    def process_chunk(self, chunk):
        from app.live.vad import SpeechSegment
        return [SpeechSegment(start_sample=0, audio=chunk)]


class FakeTranscriber:
    def __init__(self, text):
        self._text = text

    def transcribe(self, wav_path, language="id"):
        from app.asr.base import TranscriptSegmentResult
        return [TranscriptSegmentResult(start_ms=0, end_ms=500, text=self._text)]


class FakeDiarizer:
    def diarize(self, wav_path):
        return []


def test_start_feeds_queued_chunks_through_pipeline_and_reports_text_events(tmp_path):
    mic_queue = queue.Queue()
    speaker_queue = queue.Queue()
    events = []

    session = LiveSession(
        mic_transcriber=FakeTranscriber("Selamat pagi"),
        speaker_transcriber=FakeTranscriber("Mari mulai"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=mic_queue,
        speaker_queue=speaker_queue,
        diarize_interval_seconds=999,  # long enough it won't fire during this test
        on_update=events.append,
    )

    session.start()
    mic_queue.put(b"\x00\x00" * 512)
    speaker_queue.put(b"\x00\x00" * 512)

    deadline = time.time() + 5
    while len(events) < 2 and time.time() < deadline:
        time.sleep(0.05)

    session.stop()

    texts = {e["segment"].text for e in events if e["type"] == "text"}
    assert texts == {"Selamat pagi", "Mari mulai"}

    mic_segments, speaker_segments = session.get_segments()
    assert [s.text for s in mic_segments] == ["Selamat pagi"]
    assert [s.text for s in speaker_segments] == ["Mari mulai"]


def test_stop_unblocks_consumer_threads_promptly(tmp_path):
    session = LiveSession(
        mic_transcriber=FakeTranscriber("x"),
        speaker_transcriber=FakeTranscriber("y"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=queue.Queue(),
        speaker_queue=queue.Queue(),
        diarize_interval_seconds=999,
        on_update=lambda e: None,
    )
    session.start()
    start = time.time()
    session.stop()
    assert time.time() - start < 3  # stop() must not hang waiting on empty queues


class BrokenThenWorkingTranscriber:
    """Raises once (simulating a transient live-pipeline error), then works normally."""
    def __init__(self):
        self._call_count = 0

    def transcribe(self, wav_path, language="id"):
        from app.asr.base import TranscriptSegmentResult
        self._call_count += 1
        if self._call_count == 1:
            raise RuntimeError("simulated transient ASR failure")
        return [TranscriptSegmentResult(start_ms=0, end_ms=500, text="pulih setelah error")]


def test_feed_chunk_error_is_logged_and_does_not_kill_consumer_thread(tmp_path):
    mic_queue = queue.Queue()
    events = []

    session = LiveSession(
        mic_transcriber=BrokenThenWorkingTranscriber(),
        speaker_transcriber=FakeTranscriber("y"),
        diarizer=FakeDiarizer(),
        segmenter_factory=lambda: FakeSegmenter(),
        mic_wav_path=tmp_path / "mic.wav",
        speaker_wav_path=tmp_path / "speaker.wav",
        scratch_dir=tmp_path / "live_scratch",
        mic_queue=mic_queue,
        speaker_queue=queue.Queue(),
        diarize_interval_seconds=999,
        on_update=events.append,
    )

    session.start()
    mic_queue.put(b"\x00\x00" * 512)  # first chunk: transcriber raises, must not kill the thread
    mic_queue.put(b"\x00\x00" * 512)  # second chunk: thread must still be alive to process this

    deadline = time.time() + 5
    while not events and time.time() < deadline:
        time.sleep(0.05)

    session.stop()

    assert len(events) == 1
    assert events[0]["segment"].text == "pulih setelah error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/live/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.live.session'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/live/session.py
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
    ):
        self._mic_queue = mic_queue
        self._speaker_queue = speaker_queue
        self._on_update = on_update
        self._lock = threading.Lock()
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
        self._speaker_pipeline = StreamLivePipeline(
            source="speaker", segmenter=segmenter_factory(), transcriber=speaker_transcriber,
            scratch_dir=scratch_dir, samplerate=16000, on_segment=make_on_segment(self._speaker_segments),
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
        def _consume(source_queue, pipeline, source_name):
            while True:
                chunk = source_queue.get()
                if chunk is None:
                    break
                try:
                    pipeline.feed_chunk(chunk)
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
        self._diarize_loop.stop()
        self._mic_queue.put(None)
        self._speaker_queue.put(None)
        for thread in self._threads:
            thread.join(timeout=5)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/live/test_session.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/live/session.py tests/live/test_session.py
git commit -m "feat: add LiveSession wiring per-source pipelines + diarize loop"
```

---

### Task 9: Controller wiring — start/stop the live session

**Files:**
- Modify: `app/ui/controller.py`
- Test: `tests/ui/test_controller.py`

**Interfaces:**
- Consumes: `app.live.session.LiveSession` (Task 8) — via an injected factory, so the controller never constructs one directly (same dependency-injection pattern as `recorder_factory`/`finalize_fn`).
- Produces: `RecorderController.__init__` gains an optional `live_session_factory: Callable[[Path, Path, Path], "LiveSessionLike"] | None = None` param (signature: `(mic_wav_path, speaker_wav_path, scratch_dir) -> object with .start()/.stop()`). When provided:
  - `start_meeting` calls it (after the recorder starts successfully) to build a live session for this meeting's WAV paths, then calls `.start()` on it. A failure here is logged and swallowed — spec §5 says live preview failures must never block recording.
  - `stop_meeting` calls `.stop()` on the live session (if one exists) BEFORE calling `self._recorder.stop()`, so the live consumer threads release their queue references cleanly first.
  - When `live_session_factory` is `None` (not provided), behavior is byte-for-byte identical to Fase 1 — this keeps every existing Fase 1 test passing unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_controller.py (append)
class FakeLiveSession:
    def __init__(self, mic_wav_path, speaker_wav_path, scratch_dir):
        self.mic_wav_path = mic_wav_path
        self.speaker_wav_path = speaker_wav_path
        self.scratch_dir = scratch_dir
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_start_meeting_starts_live_session_when_factory_provided(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
    )

    controller.start_meeting("Rapat Live")
    assert len(created_sessions) == 1
    assert created_sessions[0].started is True

    controller.stop_meeting()
    assert created_sessions[0].stopped is True


def test_start_meeting_without_live_session_factory_behaves_like_fase1(tmp_path):
    """live_session_factory defaults to None: no live session, no behavior change."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
    )

    controller.start_meeting("Rapat Tanpa Live")
    controller.stop_meeting()
    assert controller.state == "done"


def test_live_session_construction_failure_does_not_block_recording(tmp_path):
    """spec §5: live preview must never prevent the recording itself from starting."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    def broken_live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        raise RuntimeError("silero-vad model download failed")

    async def fake_finalize_fn(**kwargs):
        from app.storage.models import Summary
        return Summary(id=1, meeting_id=kwargs["meeting_id"], mom_json="{}",
                        groq_model="llama-3.3-70b-versatile", status="ready")

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: FakeRecorder(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=broken_live_session_factory,
    )

    controller.start_meeting("Rapat Live Gagal")
    assert controller.state == "recording"  # recording still started despite live-session failure


def test_live_session_stopped_when_db_write_fails_after_it_started(tmp_path):
    """A live session that started successfully must not leak if the
    subsequent DB write for create_meeting fails. Reuses FailingSessionFactoryWrapper
    and BrokenRecorderStartThenDB, both already defined earlier in this file
    from Fase 1's Task 14."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    real_session_factory = make_session_factory(engine)

    created_sessions = []

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        live_session = FakeLiveSession(mic_wav_path, speaker_wav_path, scratch_dir)
        created_sessions.append(live_session)
        return live_session

    async def fake_finalize_fn(**kwargs):
        raise AssertionError("finalize should not be called")

    controller = RecorderController(
        session_factory=FailingSessionFactoryWrapper(real_session_factory),
        recorder_factory=lambda mic, speaker: BrokenRecorderStartThenDB(mic, speaker),
        finalize_fn=fake_finalize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
    )

    try:
        controller.start_meeting("Rapat DB Fail Live")
        assert False, "expected RuntimeError from DB"
    except RuntimeError:
        pass

    assert len(created_sessions) == 1
    assert created_sessions[0].started is True
    assert created_sessions[0].stopped is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ui/test_controller.py -v -k live_session`
Expected: FAIL with `TypeError: RecorderController.__init__() got an unexpected keyword argument 'live_session_factory'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/ui/controller.py
# Add to __init__ signature and body:
    def __init__(
        self,
        session_factory,
        recorder_factory: Callable,
        finalize_fn: Callable[..., Awaitable],
        recordings_dir: Path,
        live_session_factory: Callable[[Path, Path, Path], object] | None = None,
    ):
        self._session_factory = session_factory
        self._recorder_factory = recorder_factory
        self._finalize_fn = finalize_fn
        self._recordings_dir = recordings_dir
        self._live_session_factory = live_session_factory
        self.state = "idle"
        self.error_message: str | None = None
        self._meeting_id: int | None = None
        self._meeting_title: str | None = None
        self._recorder = None
        self._live_session = None
        self.last_docx_path: str | None = None
```

**Important ordering decision:** the live session must be constructed and
started BEFORE the recorder, not after. Task 11 (main.py wiring) needs the
live session's queues to already exist by the time `recorder_factory`
constructs the real `MicSpeakerRecorder`, since that constructor reads the
queues once at construction time — building the recorder first would hand
it queues that don't exist yet. Replace the entire `start_meeting` method
with this version (the only change from Fase 1's version is the new live
session block inserted before `recorder = self._recorder_factory(...)`,
and the two new `if self._live_session is not None: ...` cleanup lines in
the two existing except blocks):

```python
    def start_meeting(self, title: str) -> int:
        session_dirname = uuid.uuid4().hex
        meeting_dir = self._recordings_dir / session_dirname
        mic_path = meeting_dir / "mic.wav"
        speaker_path = meeting_dir / "speaker.wav"

        self._live_session = None
        if self._live_session_factory is not None:
            try:
                self._live_session = self._live_session_factory(mic_path, speaker_path, meeting_dir / "live_scratch")
                self._live_session.start()
            except Exception as exc:
                print(f"WARNING: live preview unavailable this meeting: {exc}")
                self._live_session = None

        recorder = self._recorder_factory(mic_path, speaker_path)

        try:
            recorder.start()
        except Exception as exc:
            if self._live_session is not None:
                self._live_session.stop()
                self._live_session = None
            self.error_message = f"Gagal memulai rekam (cek perangkat mic/speaker): {exc}"
            self.state = "error"
            raise

        async def _create():
            async with self._session_factory() as session:
                meeting = await repo.create_meeting(session, title, None)
                await repo.start_recording(session, meeting.id)
                await session.commit()
                return meeting.id

        try:
            meeting_id = asyncio.run(_create())
        except Exception as exc:
            recorder.stop()
            if self._live_session is not None:
                self._live_session.stop()
                self._live_session = None
            self.error_message = f"Gagal menyimpan data meeting: {exc}"
            self.state = "error"
            raise

        self._meeting_id = meeting_id
        self._meeting_title = title
        self._recorder = recorder
        self.state = "recording"
        return meeting_id
```

In `stop_meeting`, at the very top (right after the existing `if self._recorder is None: raise RuntimeError(...)` guard), add:

```python
        if self._live_session is not None:
            self._live_session.stop()
            self._live_session = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ui/test_controller.py -v`
Expected: PASS (all tests in the file, including the three new ones — existing tests keep passing since `live_session_factory` defaults to `None`)

- [ ] **Step 5: Commit**

```bash
git add app/ui/controller.py tests/ui/test_controller.py
git commit -m "feat: wire optional LiveSession start/stop into recorder controller"
```

---

### Task 10: Window — render live text and speaker relabeling

**Files:**
- Modify: `app/ui/window.py`
- Test: `tests/ui/test_window.py`

**Interfaces:**
- Consumes: nothing new from other Fase 2 tasks directly — the window only needs a thread-safe way to receive `{"type": "text", ...}` / `{"type": "relabel", ...}` events, which Task 9's `live_session_factory` wiring (constructed in Task 11/main.py) will feed via `on_update`.
- Produces: `MainWindow` gains a `queue.Queue` (`self._live_events`) that any thread can push `{"type": "text", "segment": LiveSegment}` or `{"type": "relabel", "segments": list[MergedSegment]}` onto, plus a `push_live_event(self, event: dict) -> None` method (thread-safe, callable from any thread — this is exactly what gets passed as `on_update` when wiring `LiveSession` in Task 11). A polling loop (`root.after(200, self._drain_live_events)`) started once in `__init__` drains the queue on the Tkinter main thread and updates `self.transcript_view`:
  - `"text"` event: append a new line `"{segment.text}\n"` (no label yet, per spec §4 step 3).
  - `"relabel"` event: clear `transcript_view` entirely and re-render every segment in `event["segments"]` in order as `"{label}: {text}\n"` (full re-render, per spec's simplification — acceptable since meeting-scale text volume is small).

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_window.py (append)
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_text_event_appends_unlabeled_line():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    from app.live.pipeline import LiveSegment

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "text", "segment": LiveSegment(source="mic", start_ms=0, end_ms=500, text="Selamat pagi")})
    window._drain_live_events()  # call directly instead of waiting for root.after's timer

    assert "Selamat pagi" in window.transcript_view.get("1.0", "end")

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_relabel_event_rerenders_full_transcript_with_labels():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    from app.pipeline.merge import MergedSegment

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "text", "segment": None})  # unlabeled placeholder already shown
    window._drain_live_events()

    window.push_live_event({"type": "relabel", "segments": [
        MergedSegment(source="mic", speaker_label="Anda", start_ms=0, end_ms=500, text="Selamat pagi"),
        MergedSegment(source="speaker", speaker_label="Speaker 1", start_ms=600, end_ms=1200, text="Mari mulai"),
    ]})
    window._drain_live_events()

    content = window.transcript_view.get("1.0", "end")
    assert "Anda: Selamat pagi" in content
    assert "Speaker 1: Mari mulai" in content

    root.destroy()
```

Note: the first `push_live_event({"type": "text", "segment": None})` in the second test is just to exercise that a stale unlabeled line gets fully replaced by the relabel re-render — adjust `_drain_live_events` to guard against a `None` segment gracefully (skip it) if you'd rather not special-case it in the test; either is fine as long as the relabel assertions hold.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ui/test_window.py -v -k "text_event or relabel_event"`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'push_live_event'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/ui/window.py
# Add near the top-level imports:
import queue
```

In `MainWindow.__init__`, after the existing widget-construction code, add:

```python
        self._live_events: "queue.Queue" = queue.Queue()
        self._root.after(200, self._drain_live_events)
```

Add these two new methods to `MainWindow`:

```python
    def push_live_event(self, event: dict) -> None:
        """Thread-safe: called from LiveSession's background threads."""
        self._live_events.put(event)

    def _drain_live_events(self) -> None:
        try:
            while True:
                event = self._live_events.get_nowait()
                if event["type"] == "text":
                    segment = event["segment"]
                    if segment is not None:
                        self.transcript_view.insert("end", f"{segment.text}\n")
                elif event["type"] == "relabel":
                    self.transcript_view.delete("1.0", "end")
                    for seg in event["segments"]:
                        self.transcript_view.insert("end", f"{seg.speaker_label}: {seg.text}\n")
        except queue.Empty:
            pass
        finally:
            self._root.after(200, self._drain_live_events)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ui/test_window.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add app/ui/window.py tests/ui/test_window.py
git commit -m "feat: render live transcript text and speaker relabeling in main window"
```

---

### Task 11: main.py — wire the live session factory end to end

**Files:**
- Modify: `app/main.py`
- No new automated test (pure wiring, same as Fase 1's Task 16) — verified by `import app.main` succeeding and by the manual smoke test in Step 3.

**Interfaces:**
- Consumes: everything from Tasks 1-10 (`app.live.session.LiveSession`, `app.live.vad.load_silero_vad_iterator`, `app.asr.cuda_backend.FasterWhisperBackend` / `app.asr.openvino_backend.OpenVinoWhisperBackend` with `model_size="small"`, `app.ui.window.MainWindow.push_live_event`).
- Produces: `main()` builds a small ("small"-sized) transcriber ONCE at startup (cheap enough to load eagerly, unlike the large-v3 batch model which stays lazy per Fase 1's `load_models()`), and passes a `live_session_factory` into `RecorderController` that constructs a real `LiveSession` per meeting, wired to `window.push_live_event`.

- [ ] **Step 1: Read the current file and locate the exact insertion points**

Read `app/main.py` in full before editing — `build_transcriber`, `build_models`, and `main()` all need small, precise additions; don't restructure anything else.

- [ ] **Step 2: Add a small-model builder and the LiveSession factory**

```python
# app/main.py
# Add these imports alongside the existing ones:
import queue
from app.live.session import LiveSession
from app.live.vad import SpeechSegmenter, load_silero_vad_iterator
```

Add a small-model builder mirroring `build_transcriber` (place it right after `build_transcriber`):

```python
def build_live_transcriber(backend_name: str):
    """Small model for live preview - same backend family as the batch
    transcriber, just a lighter size so it keeps up in near-real-time."""
    if backend_name == "cuda":
        return FasterWhisperBackend(model_size="small", device="cuda", compute_type="float32")
    if backend_name == "openvino":
        return OpenVinoWhisperBackend(model_size="small")
    return FasterWhisperBackend(model_size="small", device="cpu", compute_type="int8")
```

- [ ] **Step 3: Wire the LiveSession factory into `main()`**

Inside `main()`, after `backend_name = detect_backend(...)` and before `controller = RecorderController(...)`, add:

```python
    live_transcriber = None
    try:
        live_transcriber = build_live_transcriber(backend_name)
    except Exception as exc:
        print(f"WARNING: live preview model failed to load ({exc}); live preview disabled this session", file=sys.stderr)

    window_ref: dict = {}  # populated below once `window` exists; closures need this indirection

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        if live_transcriber is None:
            raise RuntimeError("live preview model not loaded")
        mic_queue: "queue.Queue" = queue.Queue(maxsize=200)
        speaker_queue: "queue.Queue" = queue.Queue(maxsize=200)
        live_diarizer = Diarizer(hf_token=settings.hf_token, device="cuda" if backend_name == "cuda" else "cpu")
        session = LiveSession(
            mic_transcriber=live_transcriber,
            speaker_transcriber=live_transcriber,
            diarizer=live_diarizer,
            segmenter_factory=lambda: SpeechSegmenter(load_silero_vad_iterator()),
            mic_wav_path=mic_wav_path,
            speaker_wav_path=speaker_wav_path,
            scratch_dir=scratch_dir,
            mic_queue=mic_queue,
            speaker_queue=speaker_queue,
            diarize_interval_seconds=8.0,
            on_update=window_ref["window"].push_live_event,
        )
        # MicSpeakerRecorder needs these same queues to actually feed audio in;
        # stash them so _real_recorder (below) can pick them up for this meeting.
        recorder_queues["mic"] = mic_queue
        recorder_queues["speaker"] = speaker_queue
        return session
```

- [ ] **Step 4: Thread the queues into the real recorder**

Replace `_real_recorder` with a version that also passes the queues stashed above:

```python
recorder_queues: dict = {"mic": None, "speaker": None}


def _real_recorder(mic_path: Path, speaker_path: Path):
    from app.audio.capture import MicSpeakerRecorder
    return MicSpeakerRecorder(
        mic_path, speaker_path,
        mic_queue=recorder_queues["mic"], speaker_queue=recorder_queues["speaker"],
    )
```

This relies on Task 9's ordering decision: `RecorderController.start_meeting` calls `live_session_factory` (populating `recorder_queues` here) BEFORE `recorder_factory` constructs the real `MicSpeakerRecorder`. As long as Task 9 was implemented as specified, `_real_recorder`'s constructor-time read of `recorder_queues["mic"]`/`["speaker"]` already sees the real queue objects — nothing further to reconcile here.

- [ ] **Step 5: Wire `window_ref` after the window is constructed**

Right after the existing `window = MainWindow(root, controller)` line, add:

```python
    window_ref["window"] = window
```

(`window_ref` must be defined — as the empty dict from Step 3 — BEFORE `controller = RecorderController(...)` is constructed, since `live_session_factory` closes over it, but it only needs a real value inside it by the time a meeting is actually started, which is always after `main()` finishes its setup and the window exists.)

- [ ] **Step 6: Pass `live_session_factory` into the controller**

```python
    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=_real_recorder,
        finalize_fn=finalize_fn,
        recordings_dir=settings.recordings_dir,
        live_session_factory=live_session_factory,
    )
```

- [ ] **Step 7: Verify import and dependencies**

```bash
./.venv/Scripts/python.exe -c "import app.main"
```
Expected: no `ImportError`/`AttributeError` (may print the live-model-loading warning if run on a machine without the live transcriber available, per spec's error-handling requirement — that's expected, not a failure).

- [ ] **Step 8: Commit**

```bash
git add app/main.py
git commit -m "feat: wire real-time live preview into the app entrypoint"
```

- [ ] **Step 9 (manual, hardware-dependent): real smoke test**

Run `./.venv/Scripts/python.exe -m app.main`, click "Mulai Rekam", speak for 20-30 seconds, and confirm:
- Unlabeled text lines appear in the transcript view within a few seconds of speaking
- After ~8 seconds, the view re-renders with "Anda:" / "Speaker N:" prefixes
- Click "Stop Rekam": live preview stops, Fase 1's batch pipeline runs as before, and the final `.docx`/DB segments are unaffected by whatever was shown live
- Query the DB mid-recording (before Stop) and confirm `is_final=False` draft rows exist; after Stop, confirm they're gone and only `is_final=True` rows remain

---

## Post-Plan Note

This plan covers Fase 2 (real-time streaming preview) only. Fase 3 (speaker
rename UI, meeting history browser, retry-failed-summary UI, and the
long-meeting diarization scaling concern noted in the design spec §7) remain
separate future plans.
