"""Audio intake: whatever the user uploads (mp3, m4a, ogg, wav...) becomes 16 kHz mono WAV,
the one format every downstream engine (Whisper, pyannote, the browser player) handles."""

import wave
from pathlib import Path

import numpy as np

TARGET_RATE = 16_000


class UnsupportedAudio(ValueError):
    pass


def is_wav(path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(12)
    return head[:4] == b"RIFF" and head[8:12] == b"WAVE"


def to_wav_16k_mono(src: Path, dst: Path) -> None:
    """Decode with PyAV (already a faster-whisper dependency, bundles its own ffmpeg libs)."""
    try:
        import av
    except ImportError as exc:
        raise UnsupportedAudio("Dekoder audio belum terpasang di server; unggah file WAV") from exc
    try:
        with av.open(str(src)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise UnsupportedAudio("File ini tidak berisi audio")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)
            with wave.open(str(dst), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(TARGET_RATE)
                for frame in container.decode(stream):
                    for f in resampler.resample(frame):
                        out.writeframes(np.ascontiguousarray(f.to_ndarray()).tobytes())
                for f in resampler.resample(None):  # flush
                    out.writeframes(np.ascontiguousarray(f.to_ndarray()).tobytes())
    except UnsupportedAudio:
        raise
    except Exception as exc:  # av raises many exception types for corrupt/unknown input
        raise UnsupportedAudio("Format audio tidak dikenali atau file rusak") from exc
