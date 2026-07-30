import time
import wave
from pathlib import Path


class WavFileWriter:
    def __init__(
        self,
        path: Path,
        samplerate: int,
        channels: int,
        sample_width: int = 2,
        flush_interval_seconds: float = 1.0,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wf = wave.open(str(path), "wb")
        self._closed = False
        self._flush_interval_seconds = flush_interval_seconds
        # Initialize to a time far in the past so the first write will flush
        self._last_flush_time = time.monotonic() - flush_interval_seconds
        try:
            self._wf.setnchannels(channels)
            self._wf.setsampwidth(sample_width)
            self._wf.setframerate(samplerate)
        except Exception:
            self._wf.close()
            raise

    def _do_flush(self) -> None:
        # wave.Wave_write buffers via its underlying file object and only
        # patches the RIFF header's size fields on close(); a concurrent
        # reader needs both the audio bytes AND the header flushed now.
        self._wf._file.flush()
        self._wf._patchheader()
        self._last_flush_time = time.monotonic()

    def write_frames(self, frames: bytes) -> None:
        self._wf.writeframes(frames)
        # ponytail: throttle flush to once per second to avoid blocking the
        # real-time audio callback thread. The data itself is never dropped;
        # only flush+patchheader calls are throttled. Task 7 polls every ~8s,
        # so 1s resolution is more than enough.
        now = time.monotonic()
        if now - self._last_flush_time >= self._flush_interval_seconds:
            self._do_flush()

    def close(self) -> None:
        # Do NOT call _do_flush() here: _patchheader() asserts the header was
        # already written, which is false for a writer that never got a frame
        # (a stream that delivered zero callbacks) -- that AssertionError used
        # to escape all the way out of "Stop Rekam". stdlib's own close()
        # already writes a zero-length header if needed, patches it, and
        # flushes; it is also a no-op the second time (it clears _file).
        if self._closed:
            return
        self._closed = True
        self._wf.close()

    def __enter__(self) -> "WavFileWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
