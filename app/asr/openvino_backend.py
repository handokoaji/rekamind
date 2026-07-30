from pathlib import Path

import numpy as np
from optimum.intel.openvino import OVModelForSpeechSeq2Seq
from transformers import WhisperProcessor

from app.asr.base import TranscriptSegmentResult


def _load_audio_array(wav_path: Path) -> tuple[np.ndarray, int]:
    """Load a WAV as mono 16kHz float32 -- what the Whisper feature extractor
    requires. Capture writes the loopback device's native format (typically
    48kHz stereo), which the extractor hard-fails on."""
    import soundfile as sf
    import torch
    import torchaudio

    audio, samplerate = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if samplerate != 16000:
        audio = torchaudio.functional.resample(torch.from_numpy(audio), samplerate, 16000).numpy()
        samplerate = 16000
    return audio, samplerate


class OpenVinoWhisperBackend:
    def __init__(self, model_size: str = "large-v3", device: str = "GPU",
                 cache_dir: Path = Path("./model_cache")):
        model_id = f"openai/whisper-{model_size}"
        # Converting whisper-large-v3 to OpenVINO IR takes many minutes, so do it
        # once and reload the saved IR on later launches. The IR is device-
        # agnostic; `device` only picks the runtime target.
        ir_path = cache_dir / f"whisper-{model_size}-ov"
        if ir_path.exists():
            self._model = OVModelForSpeechSeq2Seq.from_pretrained(ir_path, device=device)
        else:
            self._model = OVModelForSpeechSeq2Seq.from_pretrained(model_id, export=True, device=device)
            self._model.save_pretrained(ir_path)
        self._processor = WhisperProcessor.from_pretrained(model_id)

    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        audio, samplerate = _load_audio_array(wav_path)
        inputs = self._processor(audio, sampling_rate=samplerate, return_tensors="pt")
        predicted_ids = self._model.generate(inputs.input_features, language=language)
        text = self._processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        duration_ms = int(len(audio) / samplerate * 1000)
        return [TranscriptSegmentResult(start_ms=0, end_ms=duration_ms, text=text.strip())]
