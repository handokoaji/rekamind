from pathlib import Path

import numpy as np
from optimum.intel.openvino import OVModelForSpeechSeq2Seq
from transformers import WhisperProcessor

from app.asr.base import TranscriptSegmentResult


def _load_audio_array(wav_path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    audio, samplerate = sf.read(str(wav_path), dtype="float32")
    return audio, samplerate


class OpenVinoWhisperBackend:
    def __init__(self, model_size: str = "large-v3", device: str = "GPU"):
        model_id = f"openai/whisper-{model_size}"
        self._model = OVModelForSpeechSeq2Seq.from_pretrained(model_id, export=True, device=device)
        self._processor = WhisperProcessor.from_pretrained(model_id)

    def transcribe(self, wav_path: Path, language: str = "id") -> list[TranscriptSegmentResult]:
        audio, samplerate = _load_audio_array(wav_path)
        inputs = self._processor(audio, sampling_rate=samplerate, return_tensors="pt")
        predicted_ids = self._model.generate(inputs.input_features, language=language)
        text = self._processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        duration_ms = int(len(audio) / samplerate * 1000)
        return [TranscriptSegmentResult(start_ms=0, end_ms=duration_ms, text=text.strip())]
