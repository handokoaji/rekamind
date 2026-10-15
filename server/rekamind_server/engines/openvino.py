"""Transcription on an Intel GPU (integrated Arc/Iris Xe in e.g. a Core Ultra 7 155H) or Intel CPU through
OpenVINO, via optimum-intel. This is the path validated in v1 on a Core Ultra 7 155H iGPU (correct, stable
Indonesian); the NPU was evaluated and dropped (greedy decoding only, it degenerated on real speech).

Differences from the faster-whisper engine, on purpose and worth knowing:
- The Whisper feature extractor takes at most 30 s, so audio is cut into 30 s windows and each is generated on its
  own. Segment timestamps inside a window come from Whisper's timestamp tokens when the installed optimum-intel
  returns them; if not, the whole window is one segment (coarser speaker assignment, same text).
- There is no VAD: windows that are plain silence are skipped (Whisper invents text on silence).
- The glossary / initial prompt is not applied.
- The first use converts the model to OpenVINO IR (minutes, several GB of RAM); the IR is cached in the data folder.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .base import AsrSegment

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
WINDOW_SECONDS = 30.0
SILENCE_RMS = 0.003  # float32 audio in [-1, 1]; below this a whole window is treated as silence


def model_id(name: str) -> str:
    """faster-whisper style names ("large-v3", "distil-large-v3") or a full Hugging Face id."""
    if "/" in name:
        return name
    return f"distil-whisper/{name}" if name.startswith("distil-") else f"openai/whisper-{name}"


def cache_root() -> Path:
    return Path(os.environ.get("REKAMIND_DATA_DIR") or Path.home() / ".rekamind") / "openvino-models"


def ir_dir(name: str) -> Path:
    return cache_root() / (model_id(name).replace("/", "--") + "-ov")


def _read_pcm16(wav: Path) -> tuple[np.ndarray, int] | None:
    """The recorder and the server's upload conversion write PCM16 WAV; read it without extra dependencies."""
    import wave

    try:
        with wave.open(str(wav), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            ch, rate = w.getnchannels(), w.getframerate()
            data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    except (wave.Error, EOFError):
        return None
    return (data.reshape(-1, ch) if ch > 1 else data), rate


def load_audio(wav: Path) -> np.ndarray:
    """Mono 16 kHz float32. Anything not already 16 kHz mono is mixed down and linearly resampled (good enough
    for speech). Non-PCM16 files are read with soundfile, which the engine pack installs."""
    got = _read_pcm16(wav)
    if got is None:
        import soundfile as sf

        audio, rate = sf.read(str(wav), dtype="float32", always_2d=False)
    else:
        audio, rate = got
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        n = int(round(len(audio) * SAMPLE_RATE / rate))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio.astype(np.float32, copy=False)


def windows(n_samples: int) -> list[tuple[int, int]]:
    step = int(WINDOW_SECONDS * SAMPLE_RATE)
    return [(s, min(s + step, n_samples)) for s in range(0, n_samples, step)]


def is_silent(window: np.ndarray) -> bool:
    return len(window) == 0 or float(np.sqrt(np.mean(np.square(window)))) < SILENCE_RMS


def prepare_model(name: str, log: Callable[[str], None] = print) -> Path:
    """Convert and cache the OpenVINO IR (no device needed, nothing is compiled). Idempotent."""
    from optimum.intel.openvino import OVModelForSpeechSeq2Seq
    from transformers import WhisperProcessor

    out = ir_dir(name)
    if (out / "openvino_encoder_model.xml").is_file() or (out / "openvino_model.xml").is_file():
        log(f"Model sudah dikonversi: {out}")
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    mid = model_id(name)
    log(f"Mengunduh dan mengonversi {mid} …")
    model = OVModelForSpeechSeq2Seq.from_pretrained(mid, export=True, compile=False)
    model.save_pretrained(out)
    WhisperProcessor.from_pretrained(mid).save_pretrained(out)  # so later loads work offline
    log(f"Tersimpan di {out}")
    return out


class OpenVinoTranscriber:
    """Lazy and releasable, like FasterWhisperTranscriber. `device` is an OpenVINO device name: "GPU" (the Intel
    iGPU), "CPU", or "AUTO"; if the requested device cannot load the model it falls back to the CPU."""

    def __init__(self, model: str = "large-v3", device: str = "GPU"):
        self._name, self._device = model, device
        self._model = None
        self._processor = None
        self._timestamps: bool | None = None  # None = not probed yet
        self._lock = threading.Lock()
        self.active_device = ""

    def _load(self):
        with self._lock:
            if self._model is None:
                from optimum.intel.openvino import OVModelForSpeechSeq2Seq
                from transformers import WhisperProcessor

                path = prepare_model(self._name, log=lambda m: log.info(m))
                last: Exception | None = None
                for dev in dict.fromkeys([self._device, "CPU"]):
                    try:
                        log.info("loading whisper %s on OpenVINO %s", self._name, dev)
                        self._model = OVModelForSpeechSeq2Seq.from_pretrained(path, device=dev)
                        self.active_device = dev
                        break
                    except Exception as e:  # noqa: BLE001 - try the next device
                        last = e
                        log.warning("OpenVINO %s could not load the model (%s)", dev, e)
                if self._model is None:
                    raise RuntimeError(f"OpenVINO tidak bisa memuat model: {last}") from last
                self._processor = WhisperProcessor.from_pretrained(path)
            return self._model, self._processor

    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        audio = load_audio(wav)
        model, processor = self._load()
        out: list[AsrSegment] = []
        for start, end in windows(len(audio)):
            chunk = audio[start:end]
            if is_silent(chunk):
                continue
            feats = processor(chunk, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
            ids = self._generate(model, feats, language)
            out += self._segments(processor, ids, int(start / SAMPLE_RATE * 1000), int(end / SAMPLE_RATE * 1000))
        return out

    def _generate(self, model, feats, language: str):
        kw = {"language": language, "task": "transcribe"}
        if self._timestamps is not False:
            try:
                ids = model.generate(feats, return_timestamps=True, **kw)
                self._timestamps = True
                return ids
            except Exception as e:  # noqa: BLE001 - this optimum-intel build has no timestamp support
                log.info("generate(return_timestamps=True) unavailable (%s); using one segment per 30 s window", e)
                self._timestamps = False
        return model.generate(feats, **kw)

    def _segments(self, processor, ids, start_ms: int, end_ms: int) -> list[AsrSegment]:
        if self._timestamps:
            try:
                dec = processor.tokenizer.decode(ids[0], skip_special_tokens=True, output_offsets=True)
                segs = []
                for o in dec["offsets"]:
                    text = o["text"].strip()
                    if not text:
                        continue
                    t0, t1 = o["timestamp"]
                    a = start_ms + int((t0 or 0) * 1000)
                    b = start_ms + int((t1 if t1 is not None else (end_ms - start_ms) / 1000) * 1000)
                    segs.append(AsrSegment(a, min(max(b, a + 1), end_ms), text))
                if segs:
                    return segs
            except Exception as e:  # noqa: BLE001 - fall through to the plain text of the window
                log.info("could not read timestamp offsets (%s); using the whole window", e)
        text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        return [AsrSegment(start_ms, end_ms, text)] if text else []

    def release(self) -> None:
        with self._lock:
            self._model = None
            self._processor = None
        import gc

        gc.collect()
