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
