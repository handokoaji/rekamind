from unittest.mock import MagicMock

import numpy as np

from app.asr.openvino_backend import OpenVinoWhisperBackend


def test_transcribe_maps_whisper_output_to_segments(monkeypatch, tmp_path):
    fake_model = MagicMock()
    fake_model.generate.return_value = MagicMock()

    fake_processor = MagicMock()
    fake_processor.return_value.input_features = MagicMock()
    fake_processor.batch_decode.return_value = ["Selamat pagi mari kita mulai"]

    monkeypatch.setattr(
        "app.asr.openvino_backend.OVModelForSpeechSeq2Seq.from_pretrained",
        lambda *args, **kwargs: fake_model,
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend.WhisperProcessor.from_pretrained",
        lambda *args, **kwargs: fake_processor,
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend._load_audio_array",
        lambda wav_path: (np.zeros(16000, dtype=np.float32), 16000),
    )

    backend = OpenVinoWhisperBackend()
    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path, language="id")

    # Verify language parameter is forwarded to model.generate()
    fake_model.generate.assert_called_once()
    assert fake_model.generate.call_args.kwargs["language"] == "id"

    assert len(segments) == 1
    assert segments[0].text == "Selamat pagi mari kita mulai"
    assert segments[0].start_ms == 0
